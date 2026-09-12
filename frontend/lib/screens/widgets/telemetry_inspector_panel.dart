/// Live AI Telemetry, Trajectory, Session & Semantic Memory Inspector Panel.
///
/// Renders end-to-end observability across all BaroGroove AI surfaces
/// (`advisor`, `dataviz`, `forge`, `a2ui`, `mcp`), multi-turn conversations,
/// active user sessions, and extracted semantic memories.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/client.dart';
import '../../api/models.dart';
import '../../app_theme.dart';
import '../../providers.dart';

class TelemetryInspectorPanel extends ConsumerStatefulWidget {
  const TelemetryInspectorPanel({
    this.initialSummary,
    this.initialTrajectories,
    this.initialConversations,
    this.initialSessions,
    this.initialMemories,
    this.isModal = false,
    super.key,
  });

  final TelemetrySummaryModel? initialSummary;
  final List<TrajectoryRecordModel>? initialTrajectories;
  final List<ConversationRecordModel>? initialConversations;
  final List<SessionRecordModel>? initialSessions;
  final List<MemoryRecordModel>? initialMemories;
  final bool isModal;

  @override
  ConsumerState<TelemetryInspectorPanel> createState() =>
      _TelemetryInspectorPanelState();
}

class _TelemetryInspectorPanelState
    extends ConsumerState<TelemetryInspectorPanel> {
  int _activeTabIndex = 0; // 0: Trajectories, 1: Conversations, 2: Sessions, 3: Memories
  String _selectedSurface = 'All';
  String _selectedPath = 'All';
  String _memorySearchQuery = '';
  final TextEditingController _memorySearchController = TextEditingController();

  bool _loading = false;
  String? _statusBanner;

  late TelemetrySummaryModel _summary;
  late List<TrajectoryRecordModel> _trajectories;
  late List<ConversationRecordModel> _conversations;
  late List<SessionRecordModel> _sessions;
  late List<MemoryRecordModel> _memories;

  final Set<String> _expandedTrajectoryIds = <String>{};
  final Set<String> _expandedConversationIds = <String>{};

  static const List<String> _surfaceOptions = <String>[
    'All',
    'advisor',
    'dataviz',
    'forge',
    'a2ui',
    'mcp',
  ];

  static const List<String> _pathOptions = <String>[
    'All',
    'vertex-ai',
    'semantic-fallback',
    'deterministic-fallback',
  ];

  @override
  void initState() {
    super.initState();
    _summary = widget.initialSummary ?? _defaultSeedSummary();
    _trajectories = widget.initialTrajectories ?? _defaultSeedTrajectories();
    _conversations =
        widget.initialConversations ?? _defaultSeedConversations();
    _sessions = widget.initialSessions ?? _defaultSeedSessions();
    _memories = widget.initialMemories ?? _defaultSeedMemories();

    if (_trajectories.isNotEmpty) {
      _expandedTrajectoryIds.add(_trajectories.first.trajectoryId);
    }
    if (_conversations.isNotEmpty) {
      _expandedConversationIds.add(_conversations.first.conversationId);
    }

    // Fetch live data asynchronously if not purely seeded by test
    if (widget.initialSummary == null &&
        widget.initialTrajectories == null &&
        widget.initialConversations == null &&
        widget.initialSessions == null &&
        widget.initialMemories == null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _refreshAll();
      });
    }
  }

  @override
  void dispose() {
    _memorySearchController.dispose();
    super.dispose();
  }

  Future<void> _refreshAll() async {
    if (!mounted) return;
    setState(() {
      _loading = true;
      _statusBanner = null;
    });

    final BarogrooveApi api = ref.read(apiProvider);

    final results = await Future.wait<Object?>([
      api.telemetrySummary(),
      api.telemetryTrajectories(
        surface: _selectedSurface == 'All' ? null : _selectedSurface,
        modelPath: _selectedPath == 'All' ? null : _selectedPath,
      ),
      api.telemetryConversations(),
      api.telemetrySessions(
        surface: _selectedSurface == 'All' ? null : _selectedSurface,
      ),
      api.telemetryMemories(
        search: _memorySearchQuery.trim().isEmpty
            ? null
            : _memorySearchQuery.trim(),
      ),
    ]);

    if (!mounted) return;

    final ApiResult<TelemetrySummaryModel> sumRes =
        results[0] as ApiResult<TelemetrySummaryModel>;
    final ApiResult<List<TrajectoryRecordModel>> trajRes =
        results[1] as ApiResult<List<TrajectoryRecordModel>>;
    final ApiResult<List<ConversationRecordModel>> convRes =
        results[2] as ApiResult<List<ConversationRecordModel>>;
    final ApiResult<List<SessionRecordModel>> sessRes =
        results[3] as ApiResult<List<SessionRecordModel>>;
    final ApiResult<List<MemoryRecordModel>> memRes =
        results[4] as ApiResult<List<MemoryRecordModel>>;

    setState(() {
      _loading = false;
      if (sumRes.valueOrNull != null) {
        _summary = sumRes.valueOrNull!;
      }
      if (trajRes.valueOrNull != null) {
        _trajectories = trajRes.valueOrNull!;
        if (_trajectories.isNotEmpty && _expandedTrajectoryIds.isEmpty) {
          _expandedTrajectoryIds.add(_trajectories.first.trajectoryId);
        }
      }
      if (convRes.valueOrNull != null) {
        _conversations = convRes.valueOrNull!;
        if (_conversations.isNotEmpty && _expandedConversationIds.isEmpty) {
          _expandedConversationIds.add(_conversations.first.conversationId);
        }
      }
      if (sessRes.valueOrNull != null) {
        _sessions = sessRes.valueOrNull!;
      }
      if (memRes.valueOrNull != null) {
        _memories = memRes.valueOrNull!;
      }

      if (!sumRes.isOk && !trajRes.isOk) {
        _statusBanner =
            'Live telemetry endpoint unreachable — displaying cached observability snapshot.';
      }
    });
  }

  List<TrajectoryRecordModel> get _filteredTrajectories {
    return _trajectories.where((TrajectoryRecordModel t) {
      if (_selectedSurface != 'All' &&
          t.surface.toLowerCase() != _selectedSurface.toLowerCase()) {
        return false;
      }
      if (_selectedPath != 'All' &&
          t.executionPath.toLowerCase() != _selectedPath.toLowerCase()) {
        return false;
      }
      return true;
    }).toList();
  }

  List<MemoryRecordModel> get _filteredMemories {
    final String q = _memorySearchQuery.trim().toLowerCase();
    if (q.isEmpty) return _memories;
    return _memories.where((MemoryRecordModel m) {
      return m.content.toLowerCase().contains(q) ||
          m.category.toLowerCase().contains(q) ||
          m.subject.toLowerCase().contains(q) ||
          m.tags.any((String tag) => tag.toLowerCase().contains(q));
    }).toList();
  }

  Future<void> _showAddMemoryDialog() async {
    final TextEditingController contentCtrl = TextEditingController();
    final TextEditingController subjectCtrl =
        TextEditingController(text: 'user:musical_preference');
    final TextEditingController tagsCtrl =
        TextEditingController(text: 'trip-hop, petrichor, vinyl');
    String selectedCategory = 'musical_preference';
    String selectedSentiment = 'positive';

    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext ctx) {
        return StatefulBuilder(
          builder: (BuildContext context, StateSetter setModalState) {
            return AlertDialog(
              title: const Row(
                children: <Widget>[
                  Icon(Icons.psychology_outlined, size: 22),
                  SizedBox(width: BgSpace.sm),
                  Text('Add Semantic Memory'),
                ],
              ),
              content: SizedBox(
                width: 460,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    TextField(
                      controller: contentCtrl,
                      maxLines: 3,
                      decoration: const InputDecoration(
                        labelText: 'Memory Content',
                        hintText:
                            'e.g., User loves Massive Attack and low-pressure rainy trip-hop sets.',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: BgSpace.md),
                    Row(
                      children: <Widget>[
                        Expanded(
                          child: DropdownButtonFormField<String>(
                            initialValue: selectedCategory,
                            decoration: const InputDecoration(
                              labelText: 'Category',
                              border: OutlineInputBorder(),
                            ),
                            items: const <DropdownMenuItem<String>>[
                              DropdownMenuItem(
                                value: 'musical_preference',
                                child: Text('Musical Preference'),
                              ),
                              DropdownMenuItem(
                                value: 'artist_affinity',
                                child: Text('Artist Affinity'),
                              ),
                              DropdownMenuItem(
                                value: 'weather_mood',
                                child: Text('Weather-Mood Link'),
                              ),
                              DropdownMenuItem(
                                value: 'landmark_preference',
                                child: Text('Street-Art Landmark'),
                              ),
                            ],
                            onChanged: (String? v) {
                              if (v != null) {
                                setModalState(() => selectedCategory = v);
                              }
                            },
                          ),
                        ),
                        const SizedBox(width: BgSpace.md),
                        Expanded(
                          child: DropdownButtonFormField<String>(
                            initialValue: selectedSentiment,
                            decoration: const InputDecoration(
                              labelText: 'Sentiment',
                              border: OutlineInputBorder(),
                            ),
                            items: const <DropdownMenuItem<String>>[
                              DropdownMenuItem(
                                value: 'positive',
                                child: Text('Positive'),
                              ),
                              DropdownMenuItem(
                                value: 'neutral',
                                child: Text('Neutral'),
                              ),
                              DropdownMenuItem(
                                value: 'negative',
                                child: Text('Negative'),
                              ),
                            ],
                            onChanged: (String? v) {
                              if (v != null) {
                                setModalState(() => selectedSentiment = v);
                              }
                            },
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: BgSpace.md),
                    TextField(
                      controller: subjectCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Subject Key',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: BgSpace.md),
                    TextField(
                      controller: tagsCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Tags (comma-separated)',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ],
                ),
              ),
              actions: <Widget>[
                TextButton(
                  onPressed: () => Navigator.of(ctx).pop(false),
                  child: const Text('Cancel'),
                ),
                FilledButton.icon(
                  onPressed: () => Navigator.of(ctx).pop(true),
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('Save Memory'),
                ),
              ],
            );
          },
        );
      },
    );

    if (confirmed == true && contentCtrl.text.trim().isNotEmpty) {
      final List<String> parsedTags = tagsCtrl.text
          .split(',')
          .map((String s) => s.trim())
          .where((String s) => s.isNotEmpty)
          .toList();

      final BarogrooveApi api = ref.read(apiProvider);
      final ApiResult<MemoryRecordModel> res = await api.createTelemetryMemory(
        content: contentCtrl.text.trim(),
        category: selectedCategory,
        subject: subjectCtrl.text.trim().isEmpty
            ? 'user:preference'
            : subjectCtrl.text.trim(),
        tags: parsedTags,
      );

      if (!mounted) return;
      res.when(
        ok: (MemoryRecordModel created) {
          setState(() {
            _memories = <MemoryRecordModel>[created, ..._memories];
            _summary = TelemetrySummaryModel(
              totalAiCalls: _summary.totalAiCalls,
              tokenUsage: _summary.tokenUsage,
              activeSessions: _summary.activeSessions,
              totalSessions: _summary.totalSessions,
              totalConversations: _summary.totalConversations,
              storedMemories: _memories.length,
              avgLatencyMs: _summary.avgLatencyMs,
              trajectoryCountsBySurface: _summary.trajectoryCountsBySurface,
              trajectoryCountsByPath: _summary.trajectoryCountsByPath,
              errorCount: _summary.errorCount,
            );
          });
        },
        failed: (_) {
          // Optimistically add locally if offline
          final MemoryRecordModel localMem = MemoryRecordModel(
            memoryId: 'mem_${DateTime.now().millisecondsSinceEpoch}',
            userId: 'demo',
            sourceType: 'manual_inspector',
            category: selectedCategory,
            subject: subjectCtrl.text.trim(),
            content: contentCtrl.text.trim(),
            sentiment: selectedSentiment,
            confidence: 0.95,
            tags: parsedTags,
            createdAt: DateTime.now().toUtc().toIso8601String(),
            lastReinforcedAt: DateTime.now().toUtc().toIso8601String(),
            reinforcementCount: 1,
          );
          setState(() {
            _memories = <MemoryRecordModel>[localMem, ..._memories];
          });
        },
      );
    }
  }

  Future<void> _deleteMemory(MemoryRecordModel memory) async {
    final BarogrooveApi api = ref.read(apiProvider);
    await api.deleteTelemetryMemory(memory.memoryId);
    if (!mounted) return;
    setState(() {
      _memories.removeWhere(
          (MemoryRecordModel m) => m.memoryId == memory.memoryId);
    });
  }

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: widget.isModal ? BgSpace.br : BorderRadius.zero,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          // Top Header Bar (especially useful in modal or standalone view)
          _buildHeaderBar(colors, text),
          if (_statusBanner != null) _buildStatusBanner(colors, text),

          // Live Telemetry KPI Banner
          Padding(
            padding: const EdgeInsets.fromLTRB(
                BgSpace.lg, BgSpace.md, BgSpace.lg, BgSpace.sm),
            child: _buildKpiBanner(colors, text),
          ),

          // Filter & Toolbar Controls
          Padding(
            padding: const EdgeInsets.symmetric(
                horizontal: BgSpace.lg, vertical: BgSpace.xs),
            child: _buildFilterToolbar(colors, text),
          ),

          // 4 Interactive Sub-Tabs Selector
          Padding(
            padding: const EdgeInsets.fromLTRB(
                BgSpace.lg, BgSpace.sm, BgSpace.lg, BgSpace.sm),
            child: _buildSubTabsBar(colors, text),
          ),

          const Divider(height: 1),

          // Main Tab Content Area
          Expanded(
            child: _buildActiveTabContent(colors, text),
          ),
        ],
      ),
    );
  }

  Widget _buildHeaderBar(ColorScheme colors, TextTheme text) {
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.lg, vertical: BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        border: Border(bottom: BorderSide(color: colors.outlineVariant)),
      ),
      child: Row(
        children: <Widget>[
          Container(
            padding: const EdgeInsets.all(BgSpace.sm),
            decoration: BoxDecoration(
              color: colors.primary.withValues(alpha: 0.12),
              borderRadius: BgSpace.brSm,
              border: Border.all(color: colors.primary.withValues(alpha: 0.3)),
            ),
            child: Icon(Icons.radar, color: colors.primary, size: 20),
          ),
          const SizedBox(width: BgSpace.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Wrap(
                  spacing: BgSpace.sm,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    Text(
                      'AI TELEMETRY, TRAJECTORY & MEMORY INSPECTOR',
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.6,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: BgPalette.ok.withValues(alpha: 0.15),
                        borderRadius: BgSpace.brSm,
                        border: Border.all(
                            color: BgPalette.ok.withValues(alpha: 0.4)),
                      ),
                      child: Text(
                        'W3C TRACE • DUAL-SINK',
                        style: text.labelSmall?.copyWith(
                          color: BgPalette.ok,
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  'Real-time Vertex AI Gemini 2.5 Flash & deterministic fallback traces, multi-turn sessions, and semantic user memories',
                  style: text.bodySmall?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          if (_loading)
            const Padding(
              padding: EdgeInsets.only(right: BgSpace.md),
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          IconButton(
            tooltip: 'Refresh Telemetry',
            onPressed: _loading ? null : _refreshAll,
            icon: const Icon(Icons.refresh),
          ),
          if (widget.isModal) ...<Widget>[
            const SizedBox(width: BgSpace.xs),
            IconButton(
              tooltip: 'Close Inspector',
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildStatusBanner(ColorScheme colors, TextTheme text) {
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: BgSpace.lg, vertical: BgSpace.xs),
      color: BgPalette.gold500.withValues(alpha: 0.12),
      child: Row(
        children: <Widget>[
          const Icon(Icons.info_outline, size: 16, color: BgPalette.gold500),
          const SizedBox(width: BgSpace.sm),
          Expanded(
            child: Text(
              _statusBanner!,
              style: text.bodySmall?.copyWith(color: BgPalette.gold500),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildKpiBanner(ColorScheme colors, TextTheme text) {
    final Map<String, int> surfaceCounts = _summary.trajectoryCountsBySurface;
    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Wrap(
            spacing: BgSpace.md,
            runSpacing: BgSpace.sm,
            children: <Widget>[
              _KpiMetricCard(
                title: 'Total AI Calls',
                value: '${_summary.totalAiCalls}',
                subtitle: 'Across 5 surfaces',
                icon: Icons.auto_awesome,
                accent: colors.primary,
              ),
              _KpiMetricCard(
                title: 'Total Tokens',
                value: '${_summary.tokenUsage.totalTokens}',
                subtitle:
                    '${_summary.tokenUsage.promptTokens} in / ${_summary.tokenUsage.candidateTokens} out',
                icon: Icons.token_outlined,
                accent: BgPalette.gold500,
              ),
              _KpiMetricCard(
                title: 'Avg Latency',
                value: '${_summary.avgLatencyMs.toStringAsFixed(1)} ms',
                subtitle: 'W3C Trace timed',
                icon: Icons.speed,
                accent: BgPalette.ok,
              ),
              _KpiMetricCard(
                title: 'Active Sessions',
                value: '${_summary.activeSessions}',
                subtitle: '${_summary.totalConversations} conversations',
                icon: Icons.hub_outlined,
                accent: BgPalette.sky500,
              ),
              _KpiMetricCard(
                title: 'Stored Memories',
                value: '${_memories.length}',
                subtitle: 'Semantic Almanac DNA',
                icon: Icons.psychology_outlined,
                accent: Colors.purpleAccent,
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),
          const Divider(height: 12),
          // Surface Breakdown Chips
          Wrap(
            spacing: BgSpace.sm,
            runSpacing: BgSpace.xs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: <Widget>[
              Text(
                'SURFACE BREAKDOWN:',
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                  letterSpacing: 0.7,
                  fontSize: 10,
                ),
              ),
              for (final String s in const <String>[
                'advisor',
                'dataviz',
                'forge',
                'a2ui',
                'mcp',
              ])
                _SurfaceBreakdownChip(
                  surface: s,
                  count: surfaceCounts[s] ??
                      _trajectories
                          .where((TrajectoryRecordModel t) =>
                              t.surface.toLowerCase() == s)
                          .length,
                  isSelected: _selectedSurface == s,
                  onTap: () {
                    setState(() {
                      _selectedSurface = _selectedSurface == s ? 'All' : s;
                    });
                  },
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildFilterToolbar(ColorScheme colors, TextTheme text) {
    return Wrap(
      spacing: BgSpace.md,
      runSpacing: BgSpace.sm,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: <Widget>[
        // Surface filter dropdown
        Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text('Surface:', style: text.labelSmall),
            const SizedBox(width: BgSpace.xs),
            DropdownButton<String>(
              value: _selectedSurface,
              isDense: true,
              items: _surfaceOptions
                  .map(
                    (String s) => DropdownMenuItem<String>(
                      value: s,
                      child: Text(
                        s == 'All' ? 'All Surfaces' : s.toUpperCase(),
                        style: text.bodySmall,
                      ),
                    ),
                  )
                  .toList(),
              onChanged: (String? v) {
                if (v != null) {
                  setState(() => _selectedSurface = v);
                }
              },
            ),
          ],
        ),

        // Execution path filter dropdown
        Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text('Execution Path:', style: text.labelSmall),
            const SizedBox(width: BgSpace.xs),
            DropdownButton<String>(
              value: _selectedPath,
              isDense: true,
              items: _pathOptions
                  .map(
                    (String p) => DropdownMenuItem<String>(
                      value: p,
                      child: Text(p, style: text.bodySmall),
                    ),
                  )
                  .toList(),
              onChanged: (String? v) {
                if (v != null) {
                  setState(() => _selectedPath = v);
                }
              },
            ),
          ],
        ),

        // Memory search bar
        SizedBox(
          width: 240,
          child: TextField(
            controller: _memorySearchController,
            onChanged: (String v) => setState(() => _memorySearchQuery = v),
            style: text.bodySmall,
            decoration: InputDecoration(
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(
                  horizontal: BgSpace.sm, vertical: 8),
              hintText: 'Search semantic memories...',
              prefixIcon: const Icon(Icons.search, size: 16),
              suffixIcon: _memorySearchQuery.isNotEmpty
                  ? IconButton(
                      icon: const Icon(Icons.clear, size: 14),
                      onPressed: () {
                        _memorySearchController.clear();
                        setState(() => _memorySearchQuery = '');
                      },
                    )
                  : null,
              border: OutlineInputBorder(borderRadius: BgSpace.brSm),
            ),
          ),
        ),

        // Add Memory button
        FilledButton.tonalIcon(
          onPressed: _showAddMemoryDialog,
          icon: const Icon(Icons.add, size: 16),
          label: const Text('Add Memory'),
        ),
      ],
    );
  }

  Widget _buildSubTabsBar(ColorScheme colors, TextTheme text) {
    final List<({String label, IconData icon, int count})> tabs =
        <({String label, IconData icon, int count})>[
      (
        label: 'Trajectories & Traces',
        icon: Icons.timeline,
        count: _filteredTrajectories.length,
      ),
      (
        label: 'Conversations',
        icon: Icons.forum_outlined,
        count: _conversations.length,
      ),
      (
        label: 'Sessions',
        icon: Icons.devices_outlined,
        count: _sessions.length,
      ),
      (
        label: 'Semantic Memories',
        icon: Icons.psychology_outlined,
        count: _filteredMemories.length,
      ),
    ];

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: <Widget>[
          for (int i = 0; i < tabs.length; i++)
            Padding(
              padding: const EdgeInsets.only(right: BgSpace.sm),
              child: ChoiceChip(
                selected: _activeTabIndex == i,
                onSelected: (_) => setState(() => _activeTabIndex = i),
                avatar: Icon(
                  tabs[i].icon,
                  size: 16,
                  color: _activeTabIndex == i
                      ? colors.onPrimaryContainer
                      : colors.onSurfaceVariant,
                ),
                label: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Text(tabs[i].label),
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(
                        color: _activeTabIndex == i
                            ? colors.primary.withValues(alpha: 0.2)
                            : colors.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        '${tabs[i].count}',
                        style: text.labelSmall?.copyWith(fontSize: 10),
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildActiveTabContent(ColorScheme colors, TextTheme text) {
    switch (_activeTabIndex) {
      case 0:
        return _buildTrajectoriesTab(colors, text);
      case 1:
        return _buildConversationsTab(colors, text);
      case 2:
        return _buildSessionsTab(colors, text);
      case 3:
        return _buildMemoriesTab(colors, text);
      default:
        return _buildTrajectoriesTab(colors, text);
    }
  }

  // ---------------------------------------------------------------------------
  // Sub-Tab 1: Trajectories & Traces
  // ---------------------------------------------------------------------------
  Widget _buildTrajectoriesTab(ColorScheme colors, TextTheme text) {
    final List<TrajectoryRecordModel> list = _filteredTrajectories;
    if (list.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.xl),
          child: Text(
            'No trajectories match the selected filters ($_selectedSurface / $_selectedPath).',
            style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
          ),
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.all(BgSpace.lg),
      itemCount: list.length,
      separatorBuilder: (_, __) => const SizedBox(height: BgSpace.md),
      itemBuilder: (BuildContext context, int index) {
        final TrajectoryRecordModel t = list[index];
        final bool expanded = _expandedTrajectoryIds.contains(t.trajectoryId);
        return _TrajectoryRowCard(
          trajectory: t,
          expanded: expanded,
          onToggle: () {
            setState(() {
              if (expanded) {
                _expandedTrajectoryIds.remove(t.trajectoryId);
              } else {
                _expandedTrajectoryIds.add(t.trajectoryId);
              }
            });
          },
        );
      },
    );
  }

  // ---------------------------------------------------------------------------
  // Sub-Tab 2: Conversations
  // ---------------------------------------------------------------------------
  Widget _buildConversationsTab(ColorScheme colors, TextTheme text) {
    if (_conversations.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.xl),
          child: Text(
            'No multi-turn conversations recorded yet.',
            style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
          ),
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.all(BgSpace.lg),
      itemCount: _conversations.length,
      separatorBuilder: (_, __) => const SizedBox(height: BgSpace.md),
      itemBuilder: (BuildContext context, int index) {
        final ConversationRecordModel conv = _conversations[index];
        final bool expanded =
            _expandedConversationIds.contains(conv.conversationId);
        return _ConversationThreadCard(
          conversation: conv,
          expanded: expanded,
          onToggle: () {
            setState(() {
              if (expanded) {
                _expandedConversationIds.remove(conv.conversationId);
              } else {
                _expandedConversationIds.add(conv.conversationId);
              }
            });
          },
        );
      },
    );
  }

  // ---------------------------------------------------------------------------
  // Sub-Tab 3: Sessions
  // ---------------------------------------------------------------------------
  Widget _buildSessionsTab(ColorScheme colors, TextTheme text) {
    if (_sessions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(BgSpace.xl),
          child: Text(
            'No active user sessions recorded yet.',
            style: text.bodyMedium?.copyWith(color: colors.onSurfaceVariant),
          ),
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.all(BgSpace.lg),
      itemCount: _sessions.length,
      separatorBuilder: (_, __) => const SizedBox(height: BgSpace.md),
      itemBuilder: (BuildContext context, int index) {
        final SessionRecordModel s = _sessions[index];
        return _SessionCard(session: s);
      },
    );
  }

  // ---------------------------------------------------------------------------
  // Sub-Tab 4: Semantic Memories
  // ---------------------------------------------------------------------------
  Widget _buildMemoriesTab(ColorScheme colors, TextTheme text) {
    final List<MemoryRecordModel> list = _filteredMemories;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(
              BgSpace.lg, BgSpace.md, BgSpace.lg, BgSpace.xs),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: <Widget>[
              Text(
                'EXTRACTED SEMANTIC USER MEMORIES (${list.length})',
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                  letterSpacing: 0.7,
                ),
              ),
              FilledButton.icon(
                onPressed: _showAddMemoryDialog,
                icon: const Icon(Icons.add, size: 16),
                label: const Text('Add Memory'),
              ),
            ],
          ),
        ),
        Expanded(
          child: list.isEmpty
              ? Center(
                  child: Text(
                    'No semantic memories match your filter.',
                    style: text.bodyMedium
                        ?.copyWith(color: colors.onSurfaceVariant),
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(BgSpace.lg),
                  itemCount: list.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: BgSpace.md),
                  itemBuilder: (BuildContext context, int index) {
                    final MemoryRecordModel m = list[index];
                    return _MemoryCard(
                      memory: m,
                      onDelete: () => _deleteMemory(m),
                    );
                  },
                ),
        ),
      ],
    );
  }

  // ===========================================================================
  // Seeded Default Observability Snapshot (for instant/offline inspection)
  // ===========================================================================

  static TelemetrySummaryModel _defaultSeedSummary() =>
      const TelemetrySummaryModel(
        totalAiCalls: 14,
        tokenUsage: TokenUsageModel(
          promptTokens: 4120,
          candidateTokens: 1640,
          totalTokens: 5760,
          isEstimated: false,
        ),
        activeSessions: 3,
        totalSessions: 4,
        totalConversations: 3,
        storedMemories: 5,
        avgLatencyMs: 148.2,
        trajectoryCountsBySurface: <String, int>{
          'advisor': 5,
          'dataviz': 3,
          'forge': 3,
          'a2ui': 2,
          'mcp': 1,
        },
        trajectoryCountsByPath: <String, int>{
          'vertex-ai': 9,
          'semantic-fallback': 3,
          'deterministic-fallback': 2,
        },
        errorCount: 0,
      );

  static List<TrajectoryRecordModel> _defaultSeedTrajectories() =>
      <TrajectoryRecordModel>[
        const TrajectoryRecordModel(
          trajectoryId: 'traj_adv_901f2a',
          sessionId: 'sess_web_881a',
          conversationId: 'conv_adv_4401',
          userId: 'jpaquay',
          surface: 'advisor',
          endpoint: 'POST /api/advisor/live',
          createdAt: '2026-09-12T13:20:15Z',
          latencyMs: 162.4,
          traceId: '4bf92f3577b34da6a3ce929d0e0e4736',
          spanId: '00f067aa0ba902b7',
          gcpTrace:
              'projects/netdev-firebase/traces/4bf92f3577b34da6a3ce929d0e0e4736',
          requestedModel: 'gemini-2.5-flash',
          executionPath: 'vertex-ai',
          httpStatus: 200,
          tokenUsage: TokenUsageModel(
            promptTokens: 480,
            candidateTokens: 165,
            totalTokens: 645,
            isEstimated: false,
          ),
          systemInstruction:
              'You are the BaroGroove Gemini Live 2.5 Flash Forge Advisor. Inject user memories (trip-hop, petrichor, Brussels rain front) and multi-turn context.',
          userPrompt:
              'Barometer is dropping fast in Brussels—dial in a dark petrichor trip-hop set with Massive Attack.',
          multimodalMetadata: <String, dynamic>{'audio_mime_type': 'audio/webm'},
          rawModelResponse:
              '{"reply_text": "Dropping the barometer to 994 hPa for Brussels Petrichor. Seeding Massive Attack & Portishead.", "selected_theme_id": "petrichor"}',
          parsedPlan: <String, dynamic>{
            'theme_id': 'petrichor',
            'genre_id': 'trip-hop',
            'geocache_id': 'brussels_comic_strip',
          },
          toolSteps: <ToolStepModel>[
            ToolStepModel(
              stepId: 'step_1',
              toolName: 'teleport_geocache',
              label: 'Teleport Geocache',
              detail: 'Brussels Comic Strip Route (50.8503° N, 4.3517° E)',
              latencyMs: 12.1,
            ),
            ToolStepModel(
              stepId: 'step_2',
              toolName: 'select_sonic_parameters',
              label: 'Select Sonic Parameters',
              detail: 'Theme: petrichor • Corridor: trip-hop (94 BPM)',
              latencyMs: 8.4,
            ),
            ToolStepModel(
              stepId: 'step_3',
              toolName: 'seed_from_almanac',
              label: 'Seed from Almanac',
              detail: 'Massive Attack - Teardrop, Portishead - Roads',
              latencyMs: 19.3,
            ),
            ToolStepModel(
              stepId: 'step_4',
              toolName: 'execute_forge',
              label: 'Execute Forge',
              detail: 'Forged 18-track set in 118ms',
              latencyMs: 118.0,
            ),
          ],
          extractedMemoryIds: <String>['mem_01', 'mem_02'],
        ),
        const TrajectoryRecordModel(
          trajectoryId: 'traj_dvz_772c1b',
          sessionId: 'sess_web_881a',
          conversationId: 'conv_dvz_2190',
          userId: 'jpaquay',
          surface: 'dataviz',
          endpoint: 'POST /api/dataviz/qna',
          createdAt: '2026-09-12T13:18:42Z',
          latencyMs: 134.8,
          traceId: '7ac81e2499a14bc890123456789abcdef',
          spanId: '11a178bb1cb013c8',
          gcpTrace:
              'projects/netdev-firebase/traces/7ac81e2499a14bc890123456789abcdef',
          requestedModel: 'gemini-2.5-flash',
          executionPath: 'semantic-fallback',
          httpStatus: 200,
          tokenUsage: TokenUsageModel(
            promptTokens: 320,
            candidateTokens: 110,
            totalTokens: 430,
            isEstimated: true,
          ),
          systemInstruction:
              'You are the BaroGroove DataViz QnA Agent analyzing 160,717 scrobbles.',
          userPrompt:
              'How does falling barometric pressure affect my listening tempo?',
          multimodalMetadata: <String, dynamic>{},
          rawModelResponse:
              '{"answer_text": "When surface pressure drops below 1000 hPa, your average listening tempo shifts down to 88 BPM with a 24% surge in Bristol trip-hop.", "highlight_section": "pressure_vs_bpm"}',
          parsedPlan: <String, dynamic>{
            'highlight_section': 'pressure_vs_bpm',
            'key_metric_badge': '88 BPM • Low Pressure Correlation',
          },
          toolSteps: <ToolStepModel>[
            ToolStepModel(
              stepId: 'step_1',
              toolName: 'highlight_section',
              label: 'Highlight Section',
              detail: 'pressure_vs_bpm (Isobar vs Tempo scatter)',
              latencyMs: 4.5,
            ),
          ],
          extractedMemoryIds: <String>['mem_03'],
        ),
      ];

  static List<ConversationRecordModel> _defaultSeedConversations() =>
      <ConversationRecordModel>[
        const ConversationRecordModel(
          conversationId: 'conv_adv_4401',
          sessionId: 'sess_web_881a',
          userId: 'jpaquay',
          surface: 'advisor',
          title: 'Brussels Rain Front & Petrichor Trip-Hop',
          summary:
              'Multi-turn voice & text session configuring low-pressure Bristol trip-hop sets.',
          createdAt: '2026-09-12T13:15:00Z',
          updatedAt: '2026-09-12T13:20:15Z',
          turns: <ConversationTurnModel>[
            ConversationTurnModel(
              turnId: 'turn_1',
              turnIndex: 0,
              role: 'user',
              timestamp: '2026-09-12T13:15:00Z',
              content:
                  'Barometer is dropping fast in Brussels—dial in a dark petrichor trip-hop set with Massive Attack.',
              actionsExecuted: <String>[],
            ),
            ConversationTurnModel(
              turnId: 'turn_2',
              turnIndex: 1,
              role: 'assistant',
              timestamp: '2026-09-12T13:20:15Z',
              content:
                  'Dropping the barometer to 994 hPa for Brussels Petrichor. Seeding Massive Attack & Portishead into an 18-track set.',
              spokenSummary:
                  'Dialed in Brussels Petrichor at 994 hectopascals with Massive Attack.',
              actionsExecuted: <String>[
                'teleport_geocache',
                'select_sonic_parameters',
                'seed_from_almanac',
                'execute_forge',
              ],
              trajectoryId: 'traj_adv_901f2a',
            ),
          ],
        ),
      ];

  static List<SessionRecordModel> _defaultSeedSessions() =>
      <SessionRecordModel>[
        const SessionRecordModel(
          sessionId: 'sess_web_881a',
          userId: 'jpaquay',
          clientSurface: 'web-flutter',
          startedAt: '2026-09-12T13:10:00Z',
          lastActiveAt: '2026-09-12T13:20:15Z',
          turnCount: 4,
          activeGeocacheId: 'brussels_comic_strip',
          activeThemeId: 'petrichor',
          activeGenreId: 'trip-hop',
          conversationIds: <String>['conv_adv_4401', 'conv_dvz_2190'],
          trajectoryIds: <String>['traj_adv_901f2a', 'traj_dvz_772c1b'],
        ),
        const SessionRecordModel(
          sessionId: 'sess_a2ui_309b',
          userId: 'jpaquay',
          clientSurface: 'a2ui',
          startedAt: '2026-09-12T12:45:00Z',
          lastActiveAt: '2026-09-12T13:05:10Z',
          turnCount: 2,
          activeGeocacheId: 'reykjavik_harbor',
          activeThemeId: 'nordic_fog',
          activeGenreId: 'ambient',
          conversationIds: <String>[],
          trajectoryIds: <String>[],
        ),
      ];

  static List<MemoryRecordModel> _defaultSeedMemories() => <MemoryRecordModel>[
        const MemoryRecordModel(
          memoryId: 'mem_01',
          userId: 'jpaquay',
          conversationId: 'conv_adv_4401',
          trajectoryId: 'traj_adv_901f2a',
          sourceType: 'conversation',
          category: 'musical_preference',
          subject: 'genre:trip-hop',
          content:
              'Prefers 1990s Bristol trip-hop (Massive Attack, Portishead) with deep sub-bass during falling barometer fronts.',
          sentiment: 'positive',
          confidence: 0.96,
          tags: <String>['trip-hop', 'petrichor', 'massive-attack', '90s'],
          createdAt: '2026-09-12T13:20:15Z',
          lastReinforcedAt: '2026-09-12T13:20:15Z',
          reinforcementCount: 4,
        ),
        const MemoryRecordModel(
          memoryId: 'mem_02',
          userId: 'jpaquay',
          conversationId: 'conv_adv_4401',
          trajectoryId: 'traj_adv_901f2a',
          sourceType: 'almanac_feedback',
          category: 'weather_mood',
          subject: 'theme:petrichor',
          content:
              'Strong positive feedback on tracks between 86–96 BPM when surface pressure drops below 1000 hPa.',
          sentiment: 'positive',
          confidence: 0.92,
          tags: <String>['petrichor', 'low-pressure', 'bpm-correlation'],
          createdAt: '2026-09-12T13:18:00Z',
          lastReinforcedAt: '2026-09-12T13:20:00Z',
          reinforcementCount: 3,
        ),
        const MemoryRecordModel(
          memoryId: 'mem_03',
          userId: 'jpaquay',
          sourceType: 'conversation',
          category: 'artist_affinity',
          subject: 'artist:georges_brassens',
          content:
              'High affinity for poetic Chanson Française (Georges Brassens, Serge Gainsbourg) during morning solar ascent.',
          sentiment: 'positive',
          confidence: 0.94,
          tags: <String>['chanson-francaise', 'brassens', 'morning'],
          createdAt: '2026-09-12T12:30:00Z',
          lastReinforcedAt: '2026-09-12T12:30:00Z',
          reinforcementCount: 5,
        ),
      ];
}

// =============================================================================
// Sub-Widgets for KPI Cards, Trajectory Rows, Conversations, Sessions & Memories
// =============================================================================

class _KpiMetricCard extends StatelessWidget {
  const _KpiMetricCard({
    required this.title,
    required this.value,
    required this.subtitle,
    required this.icon,
    required this.accent,
  });

  final String title;
  final String value;
  final String subtitle;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    return Container(
      width: 185,
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainer,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(icon, size: 16, color: accent),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  title.toUpperCase(),
                  style: text.labelSmall?.copyWith(
                    fontSize: 10,
                    color: colors.onSurfaceVariant,
                    letterSpacing: 0.6,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: text.titleMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            subtitle,
            style: text.bodySmall?.copyWith(
              fontSize: 11,
              color: colors.onSurfaceVariant,
            ),
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }
}

class _SurfaceBreakdownChip extends StatelessWidget {
  const _SurfaceBreakdownChip({
    required this.surface,
    required this.count,
    required this.isSelected,
    required this.onTap,
  });

  final String surface;
  final int count;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    return InkWell(
      onTap: onTap,
      borderRadius: BgSpace.brSm,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: isSelected
              ? colors.primary.withValues(alpha: 0.18)
              : colors.surfaceContainer,
          borderRadius: BgSpace.brSm,
          border: Border.all(
            color: isSelected ? colors.primary : colors.outlineVariant,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Text(
              surface.toUpperCase(),
              style: text.labelSmall?.copyWith(
                fontWeight: FontWeight.w700,
                color: isSelected ? colors.primary : colors.onSurface,
              ),
            ),
            const SizedBox(width: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(
                color: colors.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '$count',
                style: text.labelSmall?.copyWith(fontSize: 10),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TrajectoryRowCard extends StatelessWidget {
  const _TrajectoryRowCard({
    required this.trajectory,
    required this.expanded,
    required this.onToggle,
  });

  final TrajectoryRecordModel trajectory;
  final bool expanded;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;
    final bool isVertex =
        trajectory.executionPath.toLowerCase().contains('vertex');
    final Color pathColor = isVertex ? BgPalette.ok : BgPalette.gold500;

    return Container(
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(
          color: expanded ? colors.primary : colors.outlineVariant,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          // Clickable summary header row
          InkWell(
            onTap: onToggle,
            borderRadius: BgSpace.brSm,
            child: Padding(
              padding: const EdgeInsets.all(BgSpace.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      // Surface badge
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: colors.primary.withValues(alpha: 0.15),
                          borderRadius: BgSpace.brSm,
                        ),
                        child: Text(
                          trajectory.surface.toUpperCase(),
                          style: text.labelSmall?.copyWith(
                            color: colors.primary,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      const SizedBox(width: BgSpace.sm),
                      // Execution path pill
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: pathColor.withValues(alpha: 0.15),
                          borderRadius: BgSpace.brSm,
                        ),
                        child: Text(
                          trajectory.executionPath,
                          style: text.labelSmall?.copyWith(
                            color: pathColor,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: BgSpace.sm),
                      // Endpoint
                      Expanded(
                        child: Text(
                          trajectory.endpoint.isNotEmpty
                              ? trajectory.endpoint
                              : trajectory.requestedModel,
                          style: text.titleSmall?.copyWith(
                            fontFamily: 'monospace',
                            fontWeight: FontWeight.w600,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      // Latency & Tokens
                      Text(
                        '${trajectory.latencyMs.toStringAsFixed(1)} ms',
                        style: text.labelSmall?.copyWith(
                          fontFamily: 'monospace',
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(width: BgSpace.md),
                      Text(
                        '${trajectory.tokenUsage.totalTokens} tok',
                        style: text.labelSmall?.copyWith(
                          fontFamily: 'monospace',
                          color: colors.onSurfaceVariant,
                        ),
                      ),
                      const SizedBox(width: BgSpace.sm),
                      Icon(
                        expanded ? Icons.expand_less : Icons.expand_more,
                        size: 20,
                      ),
                    ],
                  ),
                  const SizedBox(height: BgSpace.xs),
                  // Prompt snippet & timestamp
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          trajectory.userPrompt.isNotEmpty
                              ? trajectory.userPrompt
                              : 'Trace ID: ${trajectory.traceId}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: text.bodySmall?.copyWith(
                            color: colors.onSurfaceVariant,
                          ),
                        ),
                      ),
                      const SizedBox(width: BgSpace.md),
                      Text(
                        trajectory.createdAt,
                        style: text.labelSmall?.copyWith(
                          fontSize: 10,
                          color: colors.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                  // Tool step chips preview
                  if (trajectory.toolSteps.isNotEmpty) ...<Widget>[
                    const SizedBox(height: BgSpace.sm),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: <Widget>[
                        for (final ToolStepModel step in trajectory.toolSteps)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 7, vertical: 2),
                            decoration: BoxDecoration(
                              color: colors.surfaceContainerHighest,
                              borderRadius: BorderRadius.circular(6),
                              border: Border.all(color: colors.outlineVariant),
                            ),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                const Icon(Icons.build_circle_outlined,
                                    size: 12),
                                const SizedBox(width: 4),
                                Text(
                                  step.toolName,
                                  style: text.labelSmall?.copyWith(
                                    fontFamily: 'monospace',
                                    fontSize: 10,
                                  ),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),

          // Expanded Full Trace Drawer
          if (expanded) ...<Widget>[
            const Divider(height: 1),
            Container(
              padding: const EdgeInsets.all(BgSpace.md),
              color: colors.surfaceContainer,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  // W3C Trace & Span Context
                  Row(
                    children: <Widget>[
                      const Icon(Icons.fingerprint, size: 16),
                      const SizedBox(width: 6),
                      Expanded(
                        child: SelectableText(
                          'trajectory_id: ${trajectory.trajectoryId}   |   W3C trace_id: ${trajectory.traceId}   |   span_id: ${trajectory.spanId}',
                          style: text.labelSmall?.copyWith(
                            fontFamily: 'monospace',
                          ),
                        ),
                      ),
                      IconButton(
                        tooltip: 'Copy W3C Trace ID',
                        icon: const Icon(Icons.copy, size: 14),
                        onPressed: () {
                          Clipboard.setData(
                            ClipboardData(text: trajectory.traceId),
                          );
                        },
                      ),
                    ],
                  ),
                  if (trajectory.gcpTrace.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(bottom: BgSpace.sm),
                      child: SelectableText(
                        'logging.googleapis.com/trace: ${trajectory.gcpTrace}',
                        style: text.labelSmall?.copyWith(
                          fontFamily: 'monospace',
                          color: colors.onSurfaceVariant,
                          fontSize: 10,
                        ),
                      ),
                    ),

                  // Token Usage Details
                  Container(
                    padding: const EdgeInsets.all(BgSpace.sm),
                    decoration: BoxDecoration(
                      color: colors.surfaceContainerLow,
                      borderRadius: BgSpace.brSm,
                      border: Border.all(color: colors.outlineVariant),
                    ),
                    child: Wrap(
                      spacing: BgSpace.lg,
                      runSpacing: BgSpace.xs,
                      alignment: WrapAlignment.spaceBetween,
                      children: <Widget>[
                        Text(
                          'Model: ${trajectory.requestedModel}',
                          style: text.labelSmall,
                        ),
                        Text(
                          'Prompt Tokens: ${trajectory.tokenUsage.promptTokens}',
                          style: text.labelSmall,
                        ),
                        Text(
                          'Candidate Tokens: ${trajectory.tokenUsage.candidateTokens}',
                          style: text.labelSmall,
                        ),
                        Text(
                          'Total Tokens: ${trajectory.tokenUsage.totalTokens} ${trajectory.tokenUsage.isEstimated ? "(Est.)" : ""}',
                          style: text.labelSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: BgSpace.md),

                  // System Instruction & User Prompt
                  if (trajectory.systemInstruction.isNotEmpty) ...<Widget>[
                    Text(
                      'SYSTEM INSTRUCTION:',
                      style: text.labelSmall?.copyWith(
                        color: colors.onSurfaceVariant,
                        letterSpacing: 0.6,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Container(
                      padding: const EdgeInsets.all(BgSpace.sm),
                      decoration: BoxDecoration(
                        color: colors.surface,
                        borderRadius: BgSpace.brSm,
                        border: Border.all(color: colors.outlineVariant),
                      ),
                      child: SelectableText(
                        trajectory.systemInstruction,
                        style: text.bodySmall?.copyWith(
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                    ),
                    const SizedBox(height: BgSpace.sm),
                  ],

                  Text(
                    'USER PROMPT / INPUT:',
                    style: text.labelSmall?.copyWith(
                      color: colors.onSurfaceVariant,
                      letterSpacing: 0.6,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.all(BgSpace.sm),
                    decoration: BoxDecoration(
                      color: colors.surface,
                      borderRadius: BgSpace.brSm,
                      border: Border.all(color: colors.outlineVariant),
                    ),
                    child: SelectableText(
                      trajectory.userPrompt.isNotEmpty
                          ? trajectory.userPrompt
                          : '(No text prompt)',
                      style: text.bodySmall,
                    ),
                  ),
                  const SizedBox(height: BgSpace.md),

                  // Step-by-step Tool Execution Waterfall
                  if (trajectory.toolSteps.isNotEmpty) ...<Widget>[
                    Text(
                      'AUTONOMOUS TOOL EXECUTION WATERFALL (${trajectory.toolSteps.length} STEPS):',
                      style: text.labelSmall?.copyWith(
                        color: colors.onSurfaceVariant,
                        letterSpacing: 0.6,
                      ),
                    ),
                    const SizedBox(height: 6),
                    for (final ToolStepModel step in trajectory.toolSteps)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: BgSpace.md, vertical: BgSpace.sm),
                          decoration: BoxDecoration(
                            color: colors.surface,
                            borderRadius: BgSpace.brSm,
                            border: Border.all(
                              color: colors.primary.withValues(alpha: 0.3),
                            ),
                          ),
                          child: Row(
                            children: <Widget>[
                              Icon(
                                Icons.check_circle_outline,
                                size: 15,
                                color: BgPalette.ok,
                              ),
                              const SizedBox(width: BgSpace.sm),
                              Text(
                                step.toolName,
                                style: text.labelSmall?.copyWith(
                                  fontFamily: 'monospace',
                                  fontWeight: FontWeight.w700,
                                  color: colors.primary,
                                ),
                              ),
                              const SizedBox(width: BgSpace.md),
                              Expanded(
                                child: Text(
                                  step.detail.isNotEmpty
                                      ? step.detail
                                      : step.label,
                                  style: text.bodySmall,
                                ),
                              ),
                              if (step.latencyMs > 0)
                                Text(
                                  '${step.latencyMs.toStringAsFixed(1)} ms',
                                  style: text.labelSmall?.copyWith(
                                    fontFamily: 'monospace',
                                    color: colors.onSurfaceVariant,
                                  ),
                                ),
                            ],
                          ),
                        ),
                      ),
                    const SizedBox(height: BgSpace.sm),
                  ],

                  // Raw / Parsed JSON Output
                  Text(
                    'MODEL RESPONSE / PARSED PLAN JSON:',
                    style: text.labelSmall?.copyWith(
                      color: colors.onSurfaceVariant,
                      letterSpacing: 0.6,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Container(
                    padding: const EdgeInsets.all(BgSpace.sm),
                    decoration: BoxDecoration(
                      color: colors.surface,
                      borderRadius: BgSpace.brSm,
                      border: Border.all(color: colors.outlineVariant),
                    ),
                    child: SelectableText(
                      trajectory.rawModelResponse.isNotEmpty
                          ? trajectory.rawModelResponse
                          : const JsonEncoder.withIndent('  ')
                              .convert(trajectory.parsedPlan),
                      style: text.bodySmall?.copyWith(
                        fontFamily: 'monospace',
                        fontSize: 11,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ConversationThreadCard extends StatelessWidget {
  const _ConversationThreadCard({
    required this.conversation,
    required this.expanded,
    required this.onToggle,
  });

  final ConversationRecordModel conversation;
  final bool expanded;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          InkWell(
            onTap: onToggle,
            borderRadius: BgSpace.brSm,
            child: Padding(
              padding: const EdgeInsets.all(BgSpace.md),
              child: Row(
                children: <Widget>[
                  Icon(Icons.forum_outlined, color: colors.primary, size: 20),
                  const SizedBox(width: BgSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(
                          conversation.title,
                          style: text.titleSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          'ID: ${conversation.conversationId} • Session: ${conversation.sessionId} • Surface: ${conversation.surface.toUpperCase()}',
                          style: text.labelSmall?.copyWith(
                            color: colors.onSurfaceVariant,
                            fontFamily: 'monospace',
                          ),
                        ),
                      ],
                    ),
                  ),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: colors.surfaceContainerHighest,
                      borderRadius: BgSpace.brSm,
                    ),
                    child: Text(
                      '${conversation.turns.length} turns',
                      style: text.labelSmall,
                    ),
                  ),
                  const SizedBox(width: BgSpace.sm),
                  Icon(expanded ? Icons.expand_less : Icons.expand_more),
                ],
              ),
            ),
          ),
          if (expanded) ...<Widget>[
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.all(BgSpace.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  for (final ConversationTurnModel turn in conversation.turns)
                    Padding(
                      padding: const EdgeInsets.only(bottom: BgSpace.sm),
                      child: Container(
                        padding: const EdgeInsets.all(BgSpace.md),
                        decoration: BoxDecoration(
                          color: turn.role == 'user'
                              ? colors.surfaceContainer
                              : colors.primary.withValues(alpha: 0.08),
                          borderRadius: BgSpace.brSm,
                          border: Border.all(
                            color: turn.role == 'user'
                                ? colors.outlineVariant
                                : colors.primary.withValues(alpha: 0.3),
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Row(
                              children: <Widget>[
                                Icon(
                                  turn.role == 'user'
                                      ? Icons.person_outline
                                      : Icons.auto_awesome,
                                  size: 14,
                                  color: turn.role == 'user'
                                      ? colors.onSurfaceVariant
                                      : colors.primary,
                                ),
                                const SizedBox(width: 6),
                                Text(
                                  turn.role.toUpperCase(),
                                  style: text.labelSmall?.copyWith(
                                    fontWeight: FontWeight.w800,
                                    color: turn.role == 'user'
                                        ? colors.onSurfaceVariant
                                        : colors.primary,
                                  ),
                                ),
                                const Spacer(),
                                if (turn.trajectoryId != null &&
                                    turn.trajectoryId!.isNotEmpty)
                                  Container(
                                    padding: const EdgeInsets.symmetric(
                                        horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: colors.surfaceContainerHighest,
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(
                                      'trace: ${turn.trajectoryId}',
                                      style: text.labelSmall?.copyWith(
                                        fontFamily: 'monospace',
                                        fontSize: 10,
                                      ),
                                    ),
                                  ),
                                const SizedBox(width: BgSpace.sm),
                                Text(
                                  turn.timestamp,
                                  style: text.labelSmall?.copyWith(
                                    fontSize: 10,
                                    color: colors.onSurfaceVariant,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 6),
                            Text(turn.content, style: text.bodySmall),
                            if (turn.spokenSummary != null &&
                                turn.spokenSummary!.isNotEmpty) ...<Widget>[
                              const SizedBox(height: 6),
                              Row(
                                children: <Widget>[
                                  const Icon(Icons.volume_up_outlined,
                                      size: 14),
                                  const SizedBox(width: 4),
                                  Expanded(
                                    child: Text(
                                      'Spoken TTS: "${turn.spokenSummary}"',
                                      style: text.bodySmall?.copyWith(
                                        fontStyle: FontStyle.italic,
                                        color: colors.onSurfaceVariant,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                            if (turn.actionsExecuted.isNotEmpty) ...<Widget>[
                              const SizedBox(height: 6),
                              Wrap(
                                spacing: 6,
                                runSpacing: 4,
                                children: <Widget>[
                                  for (final String act
                                      in turn.actionsExecuted)
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                          horizontal: 6, vertical: 2),
                                      decoration: BoxDecoration(
                                        color: colors.surfaceContainerHighest,
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: Text(
                                        act,
                                        style: text.labelSmall?.copyWith(
                                          fontFamily: 'monospace',
                                          fontSize: 10,
                                        ),
                                      ),
                                    ),
                                ],
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SessionCard extends StatelessWidget {
  const _SessionCard({required this.session});

  final SessionRecordModel session;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(Icons.devices_outlined, color: colors.primary, size: 18),
              const SizedBox(width: BgSpace.sm),
              Text(
                session.sessionId,
                style: text.titleSmall?.copyWith(
                  fontFamily: 'monospace',
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(width: BgSpace.md),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: colors.primary.withValues(alpha: 0.14),
                  borderRadius: BgSpace.brSm,
                ),
                child: Text(
                  session.clientSurface.toUpperCase(),
                  style: text.labelSmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const Spacer(),
              Text(
                '${session.turnCount} turns',
                style: text.labelSmall?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: BgSpace.sm),
          Wrap(
            spacing: BgSpace.md,
            runSpacing: BgSpace.xs,
            children: <Widget>[
              Text(
                'User: ${session.userId}',
                style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
              ),
              if (session.activeGeocacheId != null)
                Text(
                  'Geocache: ${session.activeGeocacheId}',
                  style: text.bodySmall,
                ),
              if (session.activeThemeId != null)
                Text(
                  'Theme: ${session.activeThemeId}',
                  style: text.bodySmall,
                ),
              if (session.activeGenreId != null)
                Text(
                  'Genre Corridor: ${session.activeGenreId}',
                  style: text.bodySmall,
                ),
              Text(
                'Last Active: ${session.lastActiveAt}',
                style: text.bodySmall?.copyWith(color: colors.onSurfaceVariant),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MemoryCard extends StatelessWidget {
  const _MemoryCard({
    required this.memory,
    required this.onDelete,
  });

  final MemoryRecordModel memory;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final ColorScheme colors = Theme.of(context).colorScheme;
    final TextTheme text = Theme.of(context).textTheme;

    final Color sentimentColor = switch (memory.sentiment.toLowerCase()) {
      'positive' => BgPalette.ok,
      'negative' => BgPalette.danger,
      _ => BgPalette.gold500,
    };

    return Container(
      padding: const EdgeInsets.all(BgSpace.md),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BgSpace.brSm,
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: colors.primary.withValues(alpha: 0.14),
                  borderRadius: BgSpace.brSm,
                ),
                child: Text(
                  memory.category.toUpperCase(),
                  style: text.labelSmall?.copyWith(
                    color: colors.primary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: sentimentColor.withValues(alpha: 0.14),
                  borderRadius: BgSpace.brSm,
                ),
                child: Text(
                  memory.sentiment.toUpperCase(),
                  style: text.labelSmall?.copyWith(
                    color: sentimentColor,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              Text(
                '${(memory.confidence * 100).round()}% confidence',
                style: text.labelSmall?.copyWith(
                  fontFamily: 'monospace',
                  color: colors.onSurfaceVariant,
                ),
              ),
              const SizedBox(width: BgSpace.sm),
              Text(
                '• ${memory.reinforcementCount}x reinforced',
                style: text.labelSmall?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
              const Spacer(),
              IconButton(
                tooltip: 'Delete Memory',
                icon: const Icon(Icons.delete_outline, size: 18),
                color: colors.onSurfaceVariant,
                onPressed: onDelete,
              ),
            ],
          ),
          const SizedBox(height: BgSpace.xs),
          Text(
            memory.content,
            style: text.bodyMedium?.copyWith(fontWeight: FontWeight.w500),
          ),
          const SizedBox(height: BgSpace.sm),
          Row(
            children: <Widget>[
              Expanded(
                child: Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: <Widget>[
                    for (final String tag in memory.tags)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: colors.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          '#$tag',
                          style: text.labelSmall?.copyWith(fontSize: 10),
                        ),
                      ),
                  ],
                ),
              ),
              Text(
                memory.subject,
                style: text.labelSmall?.copyWith(
                  fontFamily: 'monospace',
                  color: colors.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
