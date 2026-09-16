import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/models/course.dart';
import '../../core/theme/app_spacing.dart';
import 'courses_providers.dart';

/// Create-or-edit dialog for a [Course]. Pass an existing [course] to edit
/// it in place, or omit it to create a new one.
Future<void> showCourseEditDialog(BuildContext context, {Course? course}) {
  return showDialog<void>(context: context, builder: (context) => CourseEditDialog(course: course));
}

class CourseEditDialog extends ConsumerStatefulWidget {
  const CourseEditDialog({super.key, this.course});

  final Course? course;

  @override
  ConsumerState<CourseEditDialog> createState() => _CourseEditDialogState();
}

class _CourseEditDialogState extends ConsumerState<CourseEditDialog> {
  late final TextEditingController _name;
  late final TextEditingController _code;
  late final TextEditingController _term;
  late final TextEditingController _description;
  bool _saving = false;
  String? _error;

  bool get _isEditing => widget.course != null;

  @override
  void initState() {
    super.initState();
    final course = widget.course;
    _name = TextEditingController(text: course?.name ?? '');
    _code = TextEditingController(text: course?.code ?? '');
    _term = TextEditingController(text: course?.term ?? '');
    _description = TextEditingController(text: course?.description ?? '');
  }

  @override
  void dispose() {
    _name.dispose();
    _code.dispose();
    _term.dispose();
    _description.dispose();
    super.dispose();
  }

  String? _blankToNull(String value) => value.trim().isEmpty ? null : value.trim();

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Course name is required.');
      return;
    }

    setState(() {
      _saving = true;
      _error = null;
    });

    try {
      final notifier = ref.read(coursesProvider.notifier);
      if (_isEditing) {
        await notifier.edit(
          widget.course!.id,
          name: name,
          code: _blankToNull(_code.text),
          term: _blankToNull(_term.text),
          description: _blankToNull(_description.text),
        );
      } else {
        await notifier.create(
          name: name,
          code: _blankToNull(_code.text),
          term: _blankToNull(_term.text),
          description: _blankToNull(_description.text),
        );
      }
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (e) {
      setState(() {
        _saving = false;
        _error = e.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(_isEditing ? 'Edit course' : 'New course'),
      content: SizedBox(
        width: 360,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _name,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Name'),
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: AppSpacing.sm),
            TextField(controller: _code, decoration: const InputDecoration(labelText: 'Code (optional)')),
            const SizedBox(height: AppSpacing.sm),
            TextField(controller: _term, decoration: const InputDecoration(labelText: 'Term (optional)')),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: _description,
              decoration: const InputDecoration(labelText: 'Description (optional)'),
              maxLines: 3,
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
