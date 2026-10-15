import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_breakpoints.dart';
import '../../core/theme/app_motion.dart';
import '../chats/chats_list_view.dart';
import '../chats/chats_providers.dart';
import '../conversation/conversation_view.dart';
import '../courses/courses_list_view.dart';
import 'nav_rail.dart';
import 'study_panel.dart';

/// The adaptive four-region desktop shell (Navigation | Chats | Conversation |
/// Study panel), collapsing progressively at four breakpoints. Continuously
/// resizable: every tier uses `Expanded`/bounded widths so nothing overflows.
class AppShell extends ConsumerWidget {
  const AppShell({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: LayoutBuilder(
        builder: (context, constraints) {
          final width = constraints.maxWidth;
          if (AppBreakpoints.isPhoneWidth(width)) {
            return const _PhoneLayout();
          }
          if (width < AppBreakpoints.medium) {
            return const _CompactLayout();
          }
          if (width < AppBreakpoints.large) {
            return const _MediumLayout();
          }
          return const _LargeLayout();
        },
      ),
    );
  }
}

class _LargeLayout extends StatelessWidget {
  const _LargeLayout();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        const NavRail(),
        SizedBox(
          width: 240,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const CoursesListView(),
          ),
        ),
        SizedBox(
          width: 280,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const ChatsListView(),
          ),
        ),
        const Expanded(child: ConversationView()),
        const SizedBox(width: 300, child: StudyPanel()),
      ],
    );
  }
}

class _MediumLayout extends StatelessWidget {
  const _MediumLayout();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        const NavRail(),
        SizedBox(
          width: 220,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const CoursesListView(),
          ),
        ),
        SizedBox(
          width: 260,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
            child: const ChatsListView(),
          ),
        ),
        const Expanded(child: ConversationView()),
      ],
    );
  }
}

/// Tablet tier: Navigation and Chats collapse into one togglable panel beside
/// the conversation.
class _CompactLayout extends StatefulWidget {
  const _CompactLayout();

  @override
  State<_CompactLayout> createState() => _CompactLayoutState();
}

class _CompactLayoutState extends State<_CompactLayout> {
  bool _sidebarOpen = true;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        const NavRail(),
        AnimatedContainer(
          duration: AppMotion.normal,
          curve: AppMotion.standardCurve,
          width: _sidebarOpen ? 280 : 0,
          clipBehavior: Clip.hardEdge,
          decoration: BoxDecoration(border: Border(right: BorderSide(color: theme.colorScheme.outlineVariant))),
          // The sidebar content is laid out at a fixed 280px width via OverflowBox, and
          // the outer AnimatedContainer clips it as it shrinks. A plain SizedBox would
          // be clamped by the shrinking constraint, so the content would relayout at
          // every width and overflow mid-animation (a Row with a trailing IconButton
          // cannot shrink below the button's minimum width).
          child: const OverflowBox(
            minWidth: 280,
            maxWidth: 280,
            alignment: Alignment.centerLeft,
            child: _CombinedSidebar(),
          ),
        ),
        Expanded(
          child: Column(
            children: [
              _CompactTopBar(sidebarOpen: _sidebarOpen, onToggle: () => setState(() => _sidebarOpen = !_sidebarOpen)),
              const Expanded(child: ConversationView()),
            ],
          ),
        ),
      ],
    );
  }
}

class _CompactTopBar extends StatelessWidget {
  const _CompactTopBar({required this.sidebarOpen, required this.onToggle});

  final bool sidebarOpen;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Consumer(
      builder: (context, ref, _) {
        final chat = ref.watch(activeChatProvider);
        return Container(
          height: 48,
          padding: const EdgeInsets.symmetric(horizontal: 4),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: theme.colorScheme.outlineVariant))),
          child: Row(
            children: [
              IconButton(icon: const Icon(Icons.menu), onPressed: onToggle),
              Expanded(
                child: Text(
                  chat?.displayTitle ?? 'Study Bot',
                  style: theme.textTheme.titleSmall,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _PhoneLayout extends StatelessWidget {
  const _PhoneLayout();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Consumer(
          builder: (context, ref, _) {
            final chat = ref.watch(activeChatProvider);
            return Text(chat?.displayTitle ?? 'Study Bot');
          },
        ),
      ),
      drawer: const Drawer(child: SafeArea(child: _CombinedSidebar())),
      body: const ConversationView(),
    );
  }
}

/// Courses stacked above Chats in one scrollable column, used by the compact and
/// phone tiers.
class _CombinedSidebar extends StatelessWidget {
  const _CombinedSidebar();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      children: [
        const Expanded(flex: 1, child: CoursesListView()),
        Divider(height: 1, color: theme.colorScheme.outlineVariant),
        const Expanded(flex: 2, child: ChatsListView()),
      ],
    );
  }
}
