import 'package:flutter/material.dart';

/// A centered, minimal loading indicator for full-pane loading states
/// (connecting, history loading). Deliberately unobtrusive.
class LoadingView extends StatelessWidget {
  const LoadingView({super.key});

  @override
  Widget build(BuildContext context) {
    return const Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4)));
  }
}
