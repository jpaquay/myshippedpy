// Where the conversation lives.
//
// UX_IA_SPEC.md §6.4: "Conversation state must live above the destinations, so
// switching tabs never loses history." These providers hang off the
// `ProviderScope` at the root of `main.dart` — strictly above `AppShell`, and
// therefore above the `IndexedStack` that holds the five destinations. Tab
// switches, destination rebuilds, closing and reopening the overlay, and the
// Data Viz screen being disposed all leave this object exactly where it was.
//
// Declared here rather than in `lib/providers.dart` so the assistant owns its
// own wiring; a Riverpod provider is a global, so the file it is written in
// makes no difference to its lifetime.

import 'package:flutter/rendering.dart' show ScrollDirection;
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'assistant_controller.dart';
import 'assistant_store.dart';
import 'assistant_transport.dart';

/// The one conversation, app-wide.
final ChangeNotifierProvider<AssistantConversation> assistantConversationProvider =
    ChangeNotifierProvider<AssistantConversation>(
  (Ref ref) => AssistantConversation(),
);

/// Overridable in tests and in the Data Viz bridge.
final Provider<AssistantTransport> assistantTransportProvider =
    Provider<AssistantTransport>((Ref ref) => HttpAssistantTransport());

/// Owns the microphone and the write-confirmation rules. One per app.
final Provider<AssistantController> assistantControllerProvider =
    Provider<AssistantController>((Ref ref) {
  final AssistantController controller = AssistantController(
    store: ref.watch(assistantConversationProvider),
    transport: ref.watch(assistantTransportProvider),
  );
  ref.onDispose(controller.dispose);
  return controller;
});

/// Is the overlay open? Kept out of the store so opening the sheet is not a
/// conversation event.
final StateProvider<bool> assistantOpenProvider =
    StateProvider<bool>((Ref ref) => false);

/// §6.2 — the bubble hides on scroll-down and returns on scroll-up.
///
/// Any scrollable that is the primary content of a destination drives this.
/// Wrap it in [BubbleVisibilityScrollGuard] and it is handled.
final StateProvider<bool> bubbleVisibilityProvider =
    StateProvider<bool>((Ref ref) => true);

/// Drop this around a destination's primary scroll view and the assistant
/// bubble fades out while the user scrolls down, back in when they scroll up.
class BubbleVisibilityScrollGuard extends ConsumerWidget {
  const BubbleVisibilityScrollGuard({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return NotificationListener<UserScrollNotification>(
      onNotification: (UserScrollNotification n) {
        if (n.depth != 0) return false;
        switch (n.direction) {
          case ScrollDirection.reverse:
            _set(ref, false);
          case ScrollDirection.forward:
            _set(ref, true);
          case ScrollDirection.idle:
            break;
        }
        return false;
      },
      child: child,
    );
  }

  static void _set(WidgetRef ref, bool visible) {
    if (ref.read(bubbleVisibilityProvider) == visible) return;
    ref.read(bubbleVisibilityProvider.notifier).state = visible;
  }
}
