// The one assistant, as app chrome (UX_IA_SPEC.md §6.2 / §6.3).
//
// This replaces BOTH inline banners: `GeminiLiveAdvisorBanner` on Forge and
// `_buildGeminiLiveQnaBanner` on Data Viz. Gemini Live stops being page
// furniture — it is available from every destination, keeps one conversation
// across navigation, and never covers the tab bar or the primary CTA.
//
// Resting state (§6.2): a 56 px monochrome circle. No glow, no pulse, no
// sparkle icon. One 2 px accent ring while it is listening, speaking or
// running something.
//
// Expanded (§6.3): a bottom sheet on compact/medium at 60 % of the viewport,
// draggable 30 %–92 %, never full-screen; an anchored 380 × 560 panel on
// expanded. Header 48 / body / footer 56 in both.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app_theme.dart';
import 'assistant_action_card.dart';
import 'assistant_controller.dart';
import 'assistant_models.dart';
import 'assistant_providers.dart';
import 'assistant_store.dart';

/// Resting-state diameter (§6.2).
const double _kBubble = 56;

/// §6.3 — the anchored desktop panel.
const double _kPanelWidth = 380;
const double _kPanelHeight = 560;

/// The floating bubble, and the desktop panel it becomes.
///
/// Mounted once, as the last child of the shell's `Stack` — above the
/// `IndexedStack` and above the mini-player, but outside
/// `Scaffold.bottomNavigationBar`, so it structurally cannot overlap the tab
/// bar.
class BgAssistantBubble extends ConsumerWidget {
  const BgAssistantBubble({super.key});

  /// Bottom padding a destination's scroll view must reserve so the bubble
  /// never covers content (§6.2). One number, one token, one place.
  static double reservedBottomInset(BuildContext context) =>
      BgSpace.bubbleClearance;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool expanded = BgBreak.isExpanded(context);
    final bool open = ref.watch(assistantOpenProvider);

    if (expanded && open) {
      return const _AnchoredPanel();
    }

    final bool visible = ref.watch(bubbleVisibilityProvider);
    final AssistantConversation store =
        ref.watch(assistantConversationProvider);

    // §6.2 — hides on scroll-down, returns on scroll-up. Fade + scale to 0.8
    // over 120 ms. Nothing else moves.
    return IgnorePointer(
      ignoring: !visible,
      child: AnimatedOpacity(
        opacity: visible ? 1 : 0,
        duration: const Duration(milliseconds: 120),
        child: AnimatedScale(
          scale: visible ? 1 : 0.8,
          duration: const Duration(milliseconds: 120),
          child: _BubbleButton(
            active: store.active,
            onTap: () => openAssistant(context, ref),
          ),
        ),
      ),
    );
  }
}

/// Opens the assistant: a sheet on compact/medium, the anchored panel on
/// expanded. Public so a destination can hand off to it.
void openAssistant(BuildContext context, WidgetRef ref) {
  ref.read(assistantOpenProvider.notifier).state = true;
  if (BgBreak.isExpanded(context)) return;

  final BgColors colors = Theme.of(context).bg;
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: colors.surfaceRaised,
    // §6.3 — the page stays legible behind it.
    barrierColor: Theme.of(context).colorScheme.scrim.withValues(alpha: 0.08),
    shape: const RoundedRectangleBorder(borderRadius: BgSpace.brSheet),
    builder: (BuildContext sheetContext) => DraggableScrollableSheet(
      // Never full-screen (§6.3): 92 % leaves the header and the top of the
      // page visible, deliberately.
      initialChildSize: 0.6,
      minChildSize: 0.3,
      maxChildSize: 0.92,
      expand: false,
      builder: (BuildContext context, ScrollController controller) =>
          AssistantPanelBody(scrollController: controller),
    ),
  ).whenComplete(() {
    ref.read(assistantOpenProvider.notifier).state = false;
  });
}

class _BubbleButton extends StatelessWidget {
  const _BubbleButton({required this.active, required this.onTap});

  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    return Semantics(
      button: true,
      label: 'Assistant',
      child: Material(
        color: colors.surfaceRaised,
        shape: const CircleBorder(),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          customBorder: const CircleBorder(),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: _kBubble,
            height: _kBubble,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              // One ring. No expanding halos, nothing at rest.
              border: Border.all(
                color: active ? colors.accent : colors.hairline,
                width: active ? 2 : 1,
              ),
            ),
            child: Icon(
              Icons.forum_outlined,
              size: BgIcon.chrome,
              color: colors.inkPrimary,
            ),
          ),
        ),
      ),
    );
  }
}

class _AnchoredPanel extends StatelessWidget {
  const _AnchoredPanel();

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    return Material(
      color: colors.surfaceRaised,
      borderRadius: BgSpace.br,
      clipBehavior: Clip.antiAlias,
      child: Container(
        width: _kPanelWidth,
        height: _kPanelHeight,
        decoration: BoxDecoration(
          borderRadius: BgSpace.br,
          border: Border.all(color: colors.hairline),
        ),
        child: const AssistantPanelBody(),
      ),
    );
  }
}

/// Header (48) · message list · footer (56). Identical on both containers.
class AssistantPanelBody extends ConsumerStatefulWidget {
  const AssistantPanelBody({this.scrollController, super.key});

  final ScrollController? scrollController;

  @override
  ConsumerState<AssistantPanelBody> createState() => _AssistantPanelBodyState();
}

class _AssistantPanelBodyState extends ConsumerState<AssistantPanelBody> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _fallbackScroll = ScrollController();

  @override
  void initState() {
    super.initState();
    // Pull the capability manifest — including which functions WRITE — the
    // first time the panel is opened.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(assistantControllerProvider).loadCapabilities();
    });
  }

  @override
  void dispose() {
    _input.dispose();
    _fallbackScroll.dispose();
    super.dispose();
  }

  void _send() {
    final String text = _input.text.trim();
    if (text.isEmpty) return;
    _input.clear();
    ref.read(assistantControllerProvider).submit(text);
  }

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    final AssistantConversation store =
        ref.watch(assistantConversationProvider);
    final AssistantController controller =
        ref.watch(assistantControllerProvider);

    return Column(
      children: <Widget>[
        _Header(store: store, controller: controller),
        Divider(height: 1, thickness: 1, color: colors.hairline),
        Expanded(
          child: store.isEmpty
              ? _EmptyState(store: store, onPick: (String q) {
                  controller.submit(q);
                })
              : ListView.separated(
                  controller: widget.scrollController ?? _fallbackScroll,
                  padding: const EdgeInsets.all(BgSpace.lg),
                  itemCount: store.turns.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: BgSpace.md),
                  itemBuilder: (BuildContext context, int i) => _TurnView(
                    turn: store.turns[i],
                    controller: controller,
                  ),
                ),
        ),
        Divider(height: 1, thickness: 1, color: colors.hairline),
        _Composer(
          input: _input,
          store: store,
          controller: controller,
          onSend: _send,
        ),
      ],
    );
  }
}

class _Header extends ConsumerWidget {
  const _Header({required this.store, required this.controller});

  final AssistantConversation store;
  final AssistantController controller;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final BgColors colors = Theme.of(context).bg;
    return SizedBox(
      height: 48,
      child: Row(
        children: <Widget>[
          const SizedBox(width: BgSpace.lg),
          Expanded(
            child: Text(
              'Assistant',
              style:
                  BgText.rowTitle(context)?.copyWith(color: colors.inkPrimary),
            ),
          ),
          IconButton(
            tooltip: store.muted ? 'Unmute spoken answers' : 'Mute spoken answers',
            onPressed: controller.toggleMute,
            icon: Icon(
              store.muted ? Icons.volume_off_outlined : Icons.volume_up_outlined,
              size: BgIcon.chrome,
              color: colors.inkSecondary,
            ),
          ),
          IconButton(
            tooltip: 'Close',
            onPressed: () {
              ref.read(assistantOpenProvider.notifier).state = false;
              final NavigatorState nav = Navigator.of(context);
              if (nav.canPop()) nav.pop();
            },
            icon: Icon(
              Icons.close,
              size: BgIcon.chrome,
              color: colors.inkSecondary,
            ),
          ),
          const SizedBox(width: BgSpace.xs),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.store, required this.onPick});

  final AssistantConversation store;
  final ValueChanged<String> onPick;

  static const List<String> _starters = <String>[
    'Take me somewhere it is raining',
    'What does the sky sound like here?',
    'Forge me something for this weather',
  ];

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    final List<String> chips =
        store.suggestions.isNotEmpty ? store.suggestions : _starters;

    return Padding(
      padding: const EdgeInsets.all(BgSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            'Ask about the sky, your listening history, or tell me what to '
            'forge. Anything that changes your library is shown to you first.',
            style: BgText.body(context)?.copyWith(color: colors.inkSecondary),
          ),
          const SizedBox(height: BgSpace.md),
          Wrap(
            spacing: BgSpace.sm,
            runSpacing: BgSpace.sm,
            children: <Widget>[
              for (final String q in chips.take(3))
                OutlinedButton(
                  onPressed: () => onPick(q),
                  child: Text(q, style: BgText.meta(context)),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TurnView extends StatelessWidget {
  const _TurnView({required this.turn, required this.controller});

  final AssistantTurn turn;
  final AssistantController controller;

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;

    final AssistantAction? action = turn.action;
    if (action != null) {
      return AssistantActionCard(
        action: action,
        onConfirm: () => controller.confirm(action),
        onDecline: () => controller.decline(action),
        onEdit: (String n, String v) => controller.editArgument(action, n, v),
      );
    }

    if (turn.role == AssistantRole.user) {
      // Right-aligned, no bubble fill (§6.3).
      return Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 280),
          child: Text(
            turn.text,
            textAlign: TextAlign.right,
            style: BgText.body(context)?.copyWith(color: colors.inkPrimary),
          ),
        ),
      );
    }

    if (turn.pending) {
      return Align(
        alignment: Alignment.centerLeft,
        child: Text(
          turn.origin == AssistantOrigin.dataviz
              ? 'Querying your listening data…'
              : 'Thinking…',
          style: BgText.meta(context)?.copyWith(color: colors.inkTertiary),
        ),
      );
    }

    final Color tone = turn.error ? colors.statusDanger : colors.inkPrimary;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.all(BgSpace.md),
        decoration: BoxDecoration(
          color: colors.surfaceSunken,
          borderRadius: BgSpace.br,
          border: Border.all(
            color: turn.error ? colors.statusDanger : colors.hairline,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            if (turn.origin == AssistantOrigin.dataviz) ...<Widget>[
              Text(
                'DATA VIZ',
                style: BgText.eyebrow(context)
                    ?.copyWith(color: colors.inkTertiary),
              ),
              const SizedBox(height: BgSpace.xs),
            ],
            Text(
              turn.text,
              style: BgText.body(context)?.copyWith(color: tone),
            ),
          ],
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.input,
    required this.store,
    required this.controller,
    required this.onSend,
  });

  final TextEditingController input;
  final AssistantConversation store;
  final AssistantController controller;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final BgColors colors = Theme.of(context).bg;
    return Padding(
      padding: EdgeInsets.only(
        left: BgSpace.md,
        right: BgSpace.xs,
        bottom: MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (store.voiceUnavailable != null)
            Padding(
              padding: const EdgeInsets.only(top: BgSpace.sm),
              child: Row(
                children: <Widget>[
                  Icon(
                    Icons.mic_off_outlined,
                    size: BgIcon.inline,
                    color: colors.statusWarn,
                  ),
                  const SizedBox(width: BgSpace.xs),
                  Expanded(
                    child: Text(
                      store.voiceUnavailable!,
                      style: BgText.meta(context)
                          ?.copyWith(color: colors.statusWarn),
                    ),
                  ),
                ],
              ),
            ),
          SizedBox(
            height: 56,
            child: Row(
              children: <Widget>[
                Expanded(
                  child: TextField(
                    controller: input,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => onSend(),
                    style: BgText.body(context)
                        ?.copyWith(color: colors.inkPrimary),
                    decoration: InputDecoration(
                      border: InputBorder.none,
                      hintText: store.listening
                          ? (store.liveTranscript.isEmpty
                              ? 'Listening…'
                              : store.liveTranscript)
                          : 'Ask, or tell me what to change',
                      hintStyle: BgText.body(context)
                          ?.copyWith(color: colors.inkTertiary),
                    ),
                  ),
                ),
                IconButton(
                  tooltip: store.listening ? 'Stop listening' : 'Speak',
                  onPressed: controller.toggleListening,
                  icon: Icon(
                    store.listening ? Icons.mic : Icons.mic_none,
                    size: BgIcon.chrome,
                    color: store.listening
                        ? colors.accent
                        : colors.inkSecondary,
                  ),
                ),
                IconButton(
                  tooltip: 'Send',
                  onPressed: onSend,
                  icon: Icon(
                    Icons.arrow_upward,
                    size: BgIcon.chrome,
                    color: colors.inkSecondary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
