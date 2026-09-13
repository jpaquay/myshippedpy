/// Transport hardening: timeouts, retry policy, and stream reconnect.
///
/// The load-bearing test in this file is
/// `a POST to /api/forge is never retried` — everything else checks that the
/// transport is resilient; that one checks that it is resilient *safely*.
/// A retry that re-triggers a forge is not resilience, it is a duplicate
/// playlist and a minute of wasted upstream work.
library;

import 'dart:async';
import 'dart:convert';

import 'package:barogroove/api/client.dart';
import 'package:barogroove/api/models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// Minimal forge payload the client's decoder will accept.
Map<String, Object?> _playlistJson() => <String, Object?>{
      'id': 'pl-1',
      'title': 'Falling Barometer',
      'tracks': <Object?>[],
      'rationale': <String, Object?>{'summary': 'ok', 'degraded': <String>[]},
    };

Map<String, Object?> _jobJson({
  required String status,
  String id = 'job-1',
  bool resumed = false,
  bool withResult = false,
  String? error,
}) =>
    <String, Object?>{
      'job_id': id,
      'status': status,
      'resumed': resumed,
      'error': error,
      'playlist_id': withResult ? 'pl-1' : null,
      'created_at': '2026-09-13T17:00:00Z',
      'result': withResult
          ? <String, Object?>{'playlist': _playlistJson(), 'degraded': <String>[]}
          : null,
    };

http.Response _json(Object? body, [int code = 200]) =>
    http.Response(jsonEncode(body), code, headers: <String, String>{
      'content-type': 'application/json',
    });

void main() {
  group('retry policy', () {
    test('an idempotent GET is retried on a 5xx', () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          if (calls < 3) return _json(<String, Object?>{'error': 'boom'}, 503);
          return _json(<String, Object?>{'status': 'ok', 'degraded': <String>[]});
        }),
      );

      final ApiResult<HealthStatus> res = await _health(api);
      expect(res.isOk, isTrue);
      expect(calls, 3, reason: 'one initial attempt plus two retries');
    });

    test('a GET stops retrying at the configured budget', () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          return _json(<String, Object?>{'error': 'down'}, 500);
        }),
      );

      final ApiResult<HealthStatus> res = await _health(api);
      expect(res.isOk, isFalse);
      expect(calls, 3, reason: 'bounded: it must not retry forever');
    });

    test('a 4xx is a considered answer and is not retried', () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          return _json(<String, Object?>{'detail': 'nope'}, 400);
        }),
      );

      await _health(api);
      expect(calls, 1);
    });

    test('a POST to /api/forge is never retried', () async {
      // THE safety test. A 500 here means the backend saw the forge. If the
      // client tries again it may forge a second playlist.
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          expect(req.method, 'POST');
          return _json(<String, Object?>{'detail': 'engine wobbled'}, 503);
        }),
      );

      final ApiResult<ForgeResult> res = await api.forge(_request());
      expect(res.isOk, isFalse);
      expect(calls, 1, reason: 'a non-idempotent POST gets exactly one shot');
    });

    test('starting a forge JOB is retried, because the job id dedupes it',
        () async {
      int calls = 0;
      final Set<String?> seenJobIds = <String?>{};
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          seenJobIds.add(req.url.queryParameters['job_id']);
          if (calls < 3) return _json(<String, Object?>{'detail': 'busy'}, 503);
          return _json(_jobJson(status: 'running', id: 'key-42'));
        }),
      );

      final ApiResult<ForgeJob> res =
          await api.startForgeJob(_request(), jobId: 'key-42');

      expect(res.isOk, isTrue);
      expect(calls, 3);
      // The whole safety argument in one assertion: every attempt carried the
      // same idempotency key, so the backend collapses them into one job.
      expect(seenJobIds, <String>{'key-42'});
    });

    test('a retried forge start never produces two different job ids',
        () async {
      final List<String?> keys = <String?>[];
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          keys.add(req.url.queryParameters['job_id']);
          if (keys.length == 1) {
            return _json(<String, Object?>{'detail': 'transient'}, 502);
          }
          return _json(_jobJson(status: 'running', id: 'stable', resumed: true));
        }),
      );

      await api.startForgeJob(_request(), jobId: 'stable');
      expect(keys.length, greaterThan(1));
      expect(keys.toSet().length, 1);
    });
  });

  group('timeouts', () {
    // Every call sets `.timeout(limit)` on the underlying future, so a request
    // that never answers surfaces as a TimeoutException. These assert what the
    // client then does with it, without spending the real limit waiting.

    test('a timed-out request becomes a timeout failure, never a hang',
        () async {
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          throw TimeoutException('no answer');
        }),
      );

      final ApiResult<ForgeJob> res = await api.forgeJobStatus('slow');

      expect(res.isOk, isFalse);
      expect(res.failureOrNull!.kind, ApiFailureKind.timeout);
    });

    test('a timed-out idempotent GET retries, but a bounded number of times',
        () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          throw TimeoutException('no answer');
        }),
      );

      await _health(api);
      expect(calls, 3);
    });

    test('a timed-out forge is NOT retried', () async {
      // The subtle half of the safety rule. A timeout is the *most* tempting
      // thing to retry and the least safe: the backend may have forged
      // already and only the response was lost.
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          throw TimeoutException('no answer');
        }),
      );

      final ApiResult<ForgeResult> res = await api.forge(_request());
      expect(res.isOk, isFalse);
      expect(res.failureOrNull!.kind, ApiFailureKind.timeout);
      expect(calls, 1);
    });
  });

  group('job watch reconnects', () {
    test('a transient poll failure does not end the stream', () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          switch (calls) {
            case 1:
              return _json(_jobJson(status: 'running'));
            case 2:
              return _json(<String, Object?>{'detail': 'gateway'}, 502);
            case 3:
              return _json(<String, Object?>{'detail': 'gateway'}, 502);
            default:
              return _json(_jobJson(status: 'done', withResult: true));
          }
        }),
      );

      final List<ForgeJob> seen = await api
          .watchForgeJob('job-1', interval: const Duration(milliseconds: 1))
          .toList();

      expect(seen.first.status, ForgeJobStatus.running);
      expect(seen.last.status, ForgeJobStatus.done);
      expect(seen.last.result, isNotNull);
      expect(calls, greaterThanOrEqualTo(4),
          reason: 'it reconnected across the two failures');
    });

    test('a 404 ends the watch immediately — the job is not on this backend',
        () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          return _json(<String, Object?>{'detail': 'gone'}, 404);
        }),
      );

      await expectLater(
        api.watchForgeJob('ghost', interval: const Duration(milliseconds: 1)),
        emitsError(isA<ApiFailure<ForgeJob>>()),
      );
      expect(calls, 1, reason: 'fatal, so no backoff loop');
    });

    test('the watch gives up after a bounded run of failures', () async {
      int calls = 0;
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          calls++;
          return _json(<String, Object?>{'detail': 'still down'}, 500);
        }),
      );

      await expectLater(
        api.watchForgeJob('job-1', interval: const Duration(milliseconds: 1)),
        emitsError(isA<ApiFailure<ForgeJob>>()),
      );
      // Bounded, not infinite. Exact count is policy; the point is it stops.
      expect(calls, lessThan(60));
    }, timeout: const Timeout(Duration(seconds: 120)));

    test('the stream ends on a failed job without throwing', () async {
      final BarogrooveApi api = BarogrooveApi(
        client: MockClient((http.Request req) async {
          return _json(_jobJson(status: 'failed', error: 'the sky went blank'));
        }),
      );

      final List<ForgeJob> seen = await api
          .watchForgeJob('job-1', interval: const Duration(milliseconds: 1))
          .toList();

      expect(seen, hasLength(1));
      expect(seen.single.status, ForgeJobStatus.failed);
      expect(seen.single.error, 'the sky went blank');
    });
  });
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

Future<ApiResult<HealthStatus>> _health(BarogrooveApi api) => api.health();

ForgeRequest _request() => const ForgeRequest(
      lat: 50.8503,
      lon: 4.3517,
      trackCount: 6,
    );
