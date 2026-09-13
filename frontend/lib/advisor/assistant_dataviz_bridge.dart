// Data Viz writes into the ONE conversation (UX_IA_SPEC.md §3.4 + §6.4).
//
// The Data Viz worker left exactly one seam for this: `DataVizQnaTransport`
// in `lib/screens/dataviz/dataviz_qna_transport.dart`. Every affordance on
// that screen that can ask something — the field's submit, the send button, a
// suggestion chip, "Ask a follow-up", "Widen to all weather", dictation —
// funnels into a single transport function. Replacing that one function
// routes the whole screen into the shared store, and no widget under
// `lib/screens/dataviz/` has to change.
//
// This is a *decorator*, not a second transport: the real HTTP call is still
// `httpDataVizQnaTransport`, so the analytics answer card keeps its SQL, its
// chart spec and its row count exactly as before. What it adds is:
//
//   * the question and the answer land in the shared conversation, so opening
//     the overlay from any destination shows them;
//   * `spoken_summary` is spoken by the overlay's voice, honouring the
//     overlay's mute toggle. Auto-TTS and the mute switch were removed from
//     the Data Viz card on purpose — they are the overlay's job now (§6.1).

import '../screens/dataviz/dataviz_models.dart';
import '../screens/dataviz/dataviz_qna_transport.dart';
import 'assistant_controller.dart';
import 'assistant_models.dart';
import 'assistant_store.dart';

/// Wrap [inner] so every Data Viz question is also a turn in the shared
/// conversation, and every answer is spoken unless the overlay is muted.
DataVizQnaTransport sharedConversationDataVizTransport({
  required AssistantConversation store,
  required AssistantController controller,
  DataVizQnaTransport inner = httpDataVizQnaTransport,
}) {
  return (
    String question, {
    required DataVizQnaPhaseSink onPhase,
    String? conversationId,
  }) async {
    store.addUser(question, origin: AssistantOrigin.dataviz);
    final AssistantTurn slot =
        store.addPendingAgent(origin: AssistantOrigin.dataviz);

    try {
      final DataVizQnAResponseModel answer = await inner(
        question,
        onPhase: onPhase,
        conversationId: conversationId ?? store.conversationId,
      );
      store.settle(
        slot,
        text: answer.answerText,
        spoken: answer.spokenSummary,
      );
      if (answer.suggestedFollowups.isNotEmpty) {
        store.suggestions = answer.suggestedFollowups;
      }
      await controller.speak(answer.spokenSummary);
      return answer;
    } on DataVizQnaFailure catch (e) {
      // The answer card renders its own error; the conversation records that
      // the question was asked and did not land, rather than losing it.
      store.settle(slot, text: '${e.summary} ${e.recovery}', error: true);
      rethrow;
    }
  };
}
