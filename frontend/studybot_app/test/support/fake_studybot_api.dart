import 'package:studybot_app/core/api/api_exception.dart';
import 'package:studybot_app/core/api/connection_config.dart';
import 'package:studybot_app/core/api/studybot_api.dart';
import 'package:studybot_app/core/models/chat.dart';
import 'package:studybot_app/core/models/course.dart';
import 'package:studybot_app/core/models/health.dart';
import 'package:studybot_app/core/models/message.dart';
import 'package:studybot_app/core/models/teaching_mode.dart';

const _testConfig = ConnectionConfig(baseUrl: 'http://fake', token: 'fake-token');

/// An in-memory stand-in for [StudyBotApi] used by provider tests, so
/// notifier logic (fetch/refresh/mutate) is exercised without any real HTTP
/// traffic. Seed the lists in the constructor; call sites record via the
/// `calls` log for assertions like "listChats was called with courseId=none".
class FakeStudyBotApi extends StudyBotApi {
  FakeStudyBotApi({List<Course>? courses, List<Chat>? chats, List<TeachingModeInfo>? modes})
    : courses = courses ?? [],
      chats = chats ?? [],
      modes = modes ?? const [],
      super(_testConfig);

  final List<Course> courses;
  final List<Chat> chats;
  final List<TeachingModeInfo> modes;
  final List<String> calls = [];
  ApiException? nextError;

  /// Chat ids that simulate API_CONTRACT.md's "Lazy persistence": no
  /// database row yet, so they're excluded from [listChats] and 404 from
  /// [getChatMessages]/[getChat] until [persist] is called (as sending a
  /// first real message would, in the real backend).
  final Set<String> phantomChatIds = {};

  void persist(String chatId) => phantomChatIds.remove(chatId);

  ApiException get _chatNotFound => const ApiException(code: ApiErrorCode.chatNotFound, message: 'No such chat.');

  int _idSeed = 100;

  void _maybeThrow() {
    final error = nextError;
    if (error != null) {
      nextError = null;
      throw error;
    }
  }

  @override
  Future<EngineHealth> getHealth() async {
    calls.add('getHealth');
    _maybeThrow();
    return const EngineHealth(
      apiVersion: '1',
      status: 'ok',
      provider: 'ollama',
      model: 'qwen3:4b',
      providerReachable: true,
      modelAvailable: true,
    );
  }

  @override
  Future<List<Course>> listCourses() async {
    calls.add('listCourses');
    _maybeThrow();
    return List.of(courses);
  }

  @override
  Future<Course> createCourse({required String name, String? code, String? term, String? description}) async {
    calls.add('createCourse:$name');
    _maybeThrow();
    final course = Course(
      id: 'course-${_idSeed++}',
      name: name,
      code: code,
      term: term,
      description: description,
      createdAt: 'now',
      updatedAt: 'now',
    );
    courses.add(course);
    return course;
  }

  @override
  Future<Course> updateCourse(
    String courseId, {
    required String name,
    String? code,
    String? term,
    String? description,
  }) async {
    calls.add('updateCourse:$courseId');
    _maybeThrow();
    final index = courses.indexWhere((c) => c.id == courseId);
    final updated = Course(
      id: courseId,
      name: name,
      code: code,
      term: term,
      description: description,
      createdAt: 'now',
      updatedAt: 'now',
    );
    courses[index] = updated;
    return updated;
  }

  @override
  Future<void> deleteCourse(String courseId) async {
    calls.add('deleteCourse:$courseId');
    _maybeThrow();
    courses.removeWhere((c) => c.id == courseId);
    for (var i = 0; i < chats.length; i++) {
      if (chats[i].courseId == courseId) {
        chats[i] = chats[i].copyWith(clearCourseId: true);
      }
    }
  }

  @override
  Future<List<TeachingModeInfo>> listModes() async {
    calls.add('listModes');
    _maybeThrow();
    return List.of(modes);
  }

  @override
  Future<List<Chat>> listChats({String? courseId}) async {
    calls.add('listChats:${courseId ?? '<all>'}');
    _maybeThrow();
    final visible = chats.where((c) => !phantomChatIds.contains(c.id));
    if (courseId == null) return visible.toList();
    if (courseId == 'none') return visible.where((c) => c.courseId == null).toList();
    return visible.where((c) => c.courseId == courseId).toList();
  }

  @override
  Future<Chat> createChat({String? courseId}) async {
    calls.add('createChat:$courseId');
    _maybeThrow();
    final chat = Chat(
      id: 'chat-${_idSeed++}',
      title: null,
      courseId: courseId,
      teachingMode: modes.isNotEmpty ? modes.first.id : 'teach',
      createdAt: 'now',
      updatedAt: 'now',
    );
    chats.insert(0, chat);
    return chat;
  }

  @override
  Future<Chat> getChat(String chatId) async {
    calls.add('getChat:$chatId');
    _maybeThrow();
    if (phantomChatIds.contains(chatId)) throw _chatNotFound;
    return chats.firstWhere((c) => c.id == chatId, orElse: () => throw _chatNotFound);
  }

  final Map<String, List<ChatMessage>> messagesByChat = {};

  @override
  Future<List<ChatMessage>> getChatMessages(String chatId) async {
    calls.add('getChatMessages:$chatId');
    _maybeThrow();
    if (phantomChatIds.contains(chatId)) throw _chatNotFound;
    return List.of(messagesByChat[chatId] ?? const []);
  }

  @override
  Future<Chat> renameChat(String chatId, String title) async {
    calls.add('renameChat:$chatId:$title');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    final updated = chats[index].copyWith(title: title);
    chats[index] = updated;
    return updated;
  }

  @override
  Future<void> deleteChat(String chatId) async {
    calls.add('deleteChat:$chatId');
    _maybeThrow();
    chats.removeWhere((c) => c.id == chatId);
  }

  @override
  Future<Chat> setChatCourse(String chatId, String? courseId) async {
    calls.add('setChatCourse:$chatId:$courseId');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    final updated = chats[index].copyWith(courseId: courseId, clearCourseId: courseId == null);
    chats[index] = updated;
    return updated;
  }

  @override
  Future<TeachingModeInfo> setChatMode(String chatId, String mode) async {
    calls.add('setChatMode:$chatId:$mode');
    _maybeThrow();
    final index = chats.indexWhere((c) => c.id == chatId);
    chats[index] = chats[index].copyWith(teachingMode: mode);
    return modes.where((m) => m.id == mode).firstOrNull ??
        TeachingModeInfo(id: mode, displayName: mode, description: '');
  }
}
