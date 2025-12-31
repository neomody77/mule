import 'package:flutter/material.dart';

import '../config/theme.dart';

/// 回收站页面 - 暂时显示空状态，后续实现
class TrashScreen extends StatelessWidget {
  const TrashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      backgroundColor: isDark ? ZiaOlive.shade900 : ZiaOlive.shade50,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        title: const Text(
          'Trash',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.delete_outline,
              size: 64,
              color: ZiaOlive.shade200,
            ),
            const SizedBox(height: 16),
            Text(
              'Trash is empty',
              style: TextStyle(
                color: ZiaOlive.shade300,
                fontSize: 16,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Deleted workspaces will appear here',
              style: TextStyle(
                color: ZiaOlive.shade200,
                fontSize: 14,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
