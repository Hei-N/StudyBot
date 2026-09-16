import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../chats/chats_providers.dart';
import '../modes/mode_picker.dart';
import 'conversation_providers.dart';

/// The bottom composer: teaching-mode picker, multiline input, send button.
/// Enter sends; Shift+Enter inserts a newline. Disabled entirely while a
/// reply is streaming, and never sends blank/whitespace-only text.
class Composer extends ConsumerStatefulWidget {
  const Composer({super.key});

  @override
  ConsumerState<Composer> createState() => _ComposerState();
}

class _ComposerState extends ConsumerState<Composer> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _send(bool isSending) {
    if (isSending) return;
    final text = _controller.text;
    if (text.trim().isEmpty) return;
    ref.read(conversationProvider.notifier).send(text);
    _controller.clear();
  }

  KeyEventResult _handleKey(FocusNode node, KeyEvent event, bool isSending) {
    if (event is KeyDownEvent && event.logicalKey == LogicalKeyboardKey.enter) {
      if (HardwareKeyboard.instance.isShiftPressed) {
        return KeyEventResult.ignored;
      }
      _send(isSending);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final chat = ref.watch(activeChatProvider);
    final conversationAsync = ref.watch(conversationProvider);
    final isSending = conversationAsync.value?.isSending ?? false;
    final enabled = chat != null && !isSending;

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          const ModePicker(),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Focus(
              onKeyEvent: (node, event) => _handleKey(node, event, isSending),
              child: TextField(
                controller: _controller,
                focusNode: _focusNode,
                enabled: enabled,
                minLines: 1,
                maxLines: 6,
                textInputAction: TextInputAction.newline,
                decoration: InputDecoration(
                  hintText: chat == null ? 'Select a chat to begin' : 'Message Study Bot…',
                  border: OutlineInputBorder(borderRadius: AppRadii.lgRadius, borderSide: BorderSide.none),
                ),
                onChanged: (_) => setState(() {}),
              ),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          IconButton.filled(
            onPressed: enabled && _controller.text.trim().isNotEmpty ? () => _send(isSending) : null,
            icon: const Icon(Icons.arrow_upward),
          ),
        ],
      ),
    );
  }
}
