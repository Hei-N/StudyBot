import 'package:flutter_test/flutter_test.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/health.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/core/models/teaching_mode.dart';

void main() {
  group('Course', () {
    test('parses from full JSON', () {
      final course = Course.fromJson({
        'id': 'c1',
        'name': 'Physics I',
        'code': 'PHY 215',
        'term': 'Fall 2026',
        'description': 'Intro mechanics',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-02T00:00:00Z',
      });
      expect(course.id, 'c1');
      expect(course.name, 'Physics I');
      expect(course.subtitle, 'PHY 215 · Fall 2026');
    });

    test('subtitle omits missing code/term and is null when both absent', () {
      final withCodeOnly = Course.fromJson({
        'id': 'c1',
        'name': 'Physics I',
        'code': 'PHY 215',
        'term': null,
        'description': null,
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z',
      });
      expect(withCodeOnly.subtitle, 'PHY 215');

      final withNeither = Course.fromJson({
        'id': 'c1',
        'name': 'Physics I',
        'code': null,
        'term': null,
        'description': null,
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z',
      });
      expect(withNeither.subtitle, isNull);
    });
  });

  group('Chat', () {
    Map<String, dynamic> json({String? title, String? courseId}) => {
      'id': 'chat1',
      'title': title,
      'courseId': courseId,
      'teachingMode': 'teach',
      'reasoningMode': 'fast',
      'createdAt': '2026-01-01T00:00:00Z',
      'updatedAt': '2026-01-01T00:00:00Z',
    };

    test('parses from JSON', () {
      final chat = Chat.fromJson(json(title: 'My chat', courseId: 'c1'));
      expect(chat.id, 'chat1');
      expect(chat.title, 'My chat');
      expect(chat.courseId, 'c1');
      expect(chat.teachingMode, 'teach');
      expect(chat.reasoningMode, 'fast');
    });

    test('displayTitle falls back to Untitled for null or blank title', () {
      expect(Chat.fromJson(json(title: null)).displayTitle, 'Untitled');
      expect(Chat.fromJson(json(title: '   ')).displayTitle, 'Untitled');
      expect(Chat.fromJson(json(title: 'Named')).displayTitle, 'Named');
    });

    test('copyWith clears courseId only when requested', () {
      final chat = Chat.fromJson(json(courseId: 'c1'));
      final unchanged = chat.copyWith(title: 'New title');
      expect(unchanged.courseId, 'c1');

      final cleared = chat.copyWith(clearCourseId: true);
      expect(cleared.courseId, isNull);
    });
  });

  group('ChatMessage', () {
    test('parses a persisted message', () {
      final message = ChatMessage.fromJson({
        'id': 42,
        'role': 'assistant',
        'content': 'Hello',
        'createdAt': '2026-01-01T00:00:00Z',
      });
      expect(message.id, 42);
      expect(message.role, MessageRole.assistant);
      expect(message.isPending, isFalse);
    });

    test('throws on an unknown role', () {
      expect(
        () => ChatMessage.fromJson({'id': 1, 'role': 'system', 'content': 'x', 'createdAt': ''}),
        throwsFormatException,
      );
    });

    test('pending() has a null id and isPending true', () {
      final pending = ChatMessage.pending(role: MessageRole.user, content: 'hi');
      expect(pending.id, isNull);
      expect(pending.isPending, isTrue);
    });

    test('copyWith replaces only content', () {
      final message = ChatMessage.fromJson({
        'id': 1,
        'role': 'user',
        'content': 'old',
        'createdAt': '2026-01-01T00:00:00Z',
      });
      final updated = message.copyWith(content: 'new');
      expect(updated.content, 'new');
      expect(updated.id, message.id);
      expect(updated.createdAt, message.createdAt);
    });
  });

  group('EngineHealth', () {
    test('isHealthy requires ok status and a reachable provider', () {
      final healthy = EngineHealth.fromJson({
        'apiVersion': '1',
        'status': 'ok',
        'provider': 'ollama',
        'model': 'qwen3:4b',
        'providerReachable': true,
        'modelAvailable': true,
      });
      expect(healthy.isHealthy, isTrue);

      final unreachable = EngineHealth.fromJson({
        'apiVersion': '1',
        'status': 'ok',
        'provider': 'ollama',
        'model': 'qwen3:4b',
        'providerReachable': false,
        'modelAvailable': null,
      });
      expect(unreachable.isHealthy, isFalse);
    });
  });

  group('TeachingModeInfo', () {
    test('parses from JSON', () {
      final mode = TeachingModeInfo.fromJson({
        'id': 'teach',
        'displayName': 'Teach',
        'description': 'Step-by-step explanations',
      });
      expect(mode.id, 'teach');
      expect(mode.displayName, 'Teach');
    });
  });
}
