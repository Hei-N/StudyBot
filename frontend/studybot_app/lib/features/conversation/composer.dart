import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_radii.dart';
import '../../core/theme/app_spacing.dart';
import '../chats/chats_providers.dart';
import '../modes/mode_picker.dart';
import '../modes/reasoning_picker.dart';
import 'attachment_providers.dart';
import 'attachment_widgets.dart';
import 'conversation_providers.dart';

/// The bottom composer: a + attachment menu, teaching-mode picker, reasoning-mode picker,
/// attachment chips, multiline input, send button. Enter sends; Shift+Enter inserts a
/// newline. Disabled entirely while a reply is streaming, and never sends
/// blank/whitespace-only text.
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
    final chatId = ref.read(activeChatIdProvider);
    if (text.trim().isEmpty || chatId == null) return;
    final pending = ref.read(composerAttachmentsProvider.notifier).of(chatId);
    if (pending.any((a) => a.status == AttachmentStatus.uploading)) return;
    final ready = [
      for (final a in pending)
        if (a.status == AttachmentStatus.ready) a.toMessageAttachment(),
    ];
    ref.read(conversationProvider.notifier).send(text, attachments: ready);
    ref.read(composerAttachmentsProvider.notifier).clear(chatId);
    _controller.clear();
  }

  void _focusInput() => _focusNode.requestFocus();

  Future<void> _attach(String chatId) async {
    await ref.read(composerAttachmentsProvider.notifier).pick(chatId);
    _focusInput();
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
    final attachments = chat == null
        ? const <PendingAttachment>[]
        : ref.watch(
            composerAttachmentsProvider.select(
              (all) => all[chat.id] ?? const <PendingAttachment>[],
            ),
          );
    final uploading = attachments.any(
      (a) => a.status == AttachmentStatus.uploading,
    );

    ref.listen(attachmentNoticeProvider, (previous, next) {
      if (next == null) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(next)));
      ref.read(attachmentNoticeProvider.notifier).set(null);
    });

    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: theme.colorScheme.surface,
        border: Border(
          top: BorderSide(color: theme.colorScheme.outlineVariant),
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (chat != null)
            ComposerAttachmentBar(chatId: chat.id, onChanged: _focusInput),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              PopupMenuButton<String>(
                tooltip: 'Attach',
                enabled: enabled,
                icon: const Icon(Icons.add),
                style: IconButton.styleFrom(
                  padding: EdgeInsets.zero,
                  minimumSize: const Size(32, 40),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                onSelected: (_) => _attach(chat!.id),
                itemBuilder: (context) => const [
                  PopupMenuItem(
                    value: 'pdf',
                    child: ListTile(
                      dense: true,
                      contentPadding: EdgeInsets.zero,
                      leading: Icon(Icons.upload_file_outlined),
                      title: Text('Upload PDF'),
                    ),
                  ),
                ],
              ),
              const SizedBox(width: AppSpacing.xs),
              const ModePicker(),
              const SizedBox(width: AppSpacing.xs),
              const ReasoningPicker(),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Focus(
                  onKeyEvent: (node, event) =>
                      _handleKey(node, event, isSending),
                  child: TextField(
                    controller: _controller,
                    focusNode: _focusNode,
                    enabled: enabled,
                    minLines: 1,
                    maxLines: 6,
                    textInputAction: TextInputAction.newline,
                    decoration: InputDecoration(
                      hintText: chat == null
                          ? 'Select a chat to begin'
                          : 'Message Study Bot…',
                      border: OutlineInputBorder(
                        borderRadius: AppRadii.lgRadius,
                        borderSide: BorderSide.none,
                      ),
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              IconButton.filled(
                onPressed:
                    enabled && !uploading && _controller.text.trim().isNotEmpty
                    ? () => _send(isSending)
                    : null,
                icon: const Icon(Icons.arrow_upward),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
