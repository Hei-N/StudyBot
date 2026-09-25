import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/learning_memory.dart';
import '../../core/theme/app_spacing.dart';
import '../courses/courses_providers.dart';
import 'memory_providers.dart';

/// Create-or-edit dialog for a [LearningMemory]. Pass an existing [memory]
/// to edit it in place, or omit it to create a new one — optionally seeded
/// with [initialSummary]/[initialCourseId]/[initialSourceChatId] (used by
/// the "Save to Learning Memory" action in the conversation view).
Future<void> showMemoryEditDialog(
  BuildContext context, {
  LearningMemory? memory,
  String? initialSummary,
  String? initialCourseId,
  String? initialSourceChatId,
}) {
  return showDialog<void>(
    context: context,
    builder: (context) => MemoryEditDialog(
      memory: memory,
      initialSummary: initialSummary,
      initialCourseId: initialCourseId,
      initialSourceChatId: initialSourceChatId,
    ),
  );
}

class MemoryEditDialog extends ConsumerStatefulWidget {
  const MemoryEditDialog({
    super.key,
    this.memory,
    this.initialSummary,
    this.initialCourseId,
    this.initialSourceChatId,
  });

  final LearningMemory? memory;
  final String? initialSummary;
  final String? initialCourseId;
  final String? initialSourceChatId;

  @override
  ConsumerState<MemoryEditDialog> createState() => _MemoryEditDialogState();
}

class _MemoryEditDialogState extends ConsumerState<MemoryEditDialog> {
  late final TextEditingController _topic;
  late final TextEditingController _summary;
  String? _kind;
  String? _courseId;
  bool _saving = false;
  String? _error;

  bool get _isEditing => widget.memory != null;

  @override
  void initState() {
    super.initState();
    final memory = widget.memory;
    _topic = TextEditingController(text: memory?.topic ?? '');
    _summary = TextEditingController(text: memory?.summary ?? widget.initialSummary ?? '');
    _kind = memory?.kind;
    _courseId = memory?.courseId ?? widget.initialCourseId;
  }

  @override
  void dispose() {
    _topic.dispose();
    _summary.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final topic = _topic.text.trim();
    final summary = _summary.text.trim();
    final kind = _kind;
    if (topic.isEmpty || summary.isEmpty || kind == null) {
      setState(() => _error = 'Topic, kind, and summary are all required.');
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final notifier = ref.read(memoriesProvider.notifier);
      if (_isEditing) {
        await notifier.edit(
          widget.memory!.id,
          topic: topic,
          kind: kind,
          summary: summary,
          setCourseId: true,
          courseId: _courseId,
        );
      } else {
        await notifier.create(
          topic: topic,
          kind: kind,
          summary: summary,
          courseId: _courseId,
          sourceChatId: widget.initialSourceChatId,
        );
      }
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (e) {
      setState(() {
        _saving = false;
        _error = e.code == ApiErrorCode.memoryConflict
            ? 'A memory with this topic and kind already exists. Edit the existing one instead.'
            : e.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final kindsAsync = ref.watch(memoryKindCatalogProvider);
    final coursesAsync = ref.watch(coursesProvider);

    return AlertDialog(
      title: Text(_isEditing ? 'Edit learning memory' : 'New learning memory'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _topic,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Topic', hintText: 'e.g. Vector components'),
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: AppSpacing.sm),
            kindsAsync.when(
              loading: () => const LinearProgressIndicator(),
              error: (_, _) => const Text('Could not load memory kinds.'),
              data: (kinds) {
                _kind ??= kinds.isNotEmpty ? kinds.first.id : null;
                return DropdownButtonFormField<String>(
                  initialValue: _kind,
                  decoration: const InputDecoration(labelText: 'Kind'),
                  items: [for (final kind in kinds) DropdownMenuItem(value: kind.id, child: Text(kind.displayName))],
                  onChanged: (value) => setState(() => _kind = value),
                );
              },
            ),
            const SizedBox(height: AppSpacing.sm),
            coursesAsync.when(
              loading: () => const LinearProgressIndicator(),
              error: (_, _) => const Text('Could not load courses.'),
              data: (courses) {
                return DropdownButtonFormField<String?>(
                  initialValue: _courseId,
                  decoration: const InputDecoration(labelText: 'Course'),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('General (no course)')),
                    for (final course in courses) DropdownMenuItem(value: course.id, child: Text(course.name)),
                  ],
                  onChanged: (value) => setState(() => _courseId = value),
                );
              },
            ),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: _summary,
              decoration: const InputDecoration(labelText: 'Summary', alignLabelWithHint: true),
              maxLines: 5,
              minLines: 3,
            ),
            if (_error != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _saving ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(onPressed: _saving ? null : _save, child: Text(_isEditing ? 'Save' : 'Create')),
      ],
    );
  }
}
