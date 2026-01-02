import 'package:flutter/material.dart';

/// ZiaOlive 色系
class ZiaOlive {
  static const Color shade50 = Color(0xFFF2F4F2);   // 最浅 - 背景
  static const Color shade100 = Color(0xFFC4CCC3); // 边框、分隔线
  static const Color shade200 = Color(0xFF96A493); // 次要文字
  static const Color shade300 = Color(0xFF687C64); // 图标
  static const Color shade400 = Color(0xFF3A5435); // 主要文字
  static const Color shade500 = Color(0xFF0D2C06); // 强调、主色
  static const Color shade600 = Color(0xFF0A2304); // 按钮
  static const Color shade700 = Color(0xFF071A03); // 深色背景
  static const Color shade800 = Color(0xFF051102); // 更深
  static const Color shade900 = Color(0xFF020801); // 最深 - 纯黑

  // 语义色
  static const Color success = Color(0xFF4CAF50);
  static const Color error = Color(0xFFE53935);
  static const Color warning = Color(0xFFFFA726);
  static const Color info = Color(0xFF29B6F6);
}

/// Mule 应用主题
class MuleTheme {
  /// 亮色主题
  static ThemeData get light {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.light(
        primary: ZiaOlive.shade500,
        onPrimary: Colors.white,
        primaryContainer: ZiaOlive.shade100,
        onPrimaryContainer: ZiaOlive.shade500,
        secondary: ZiaOlive.shade400,
        onSecondary: Colors.white,
        surface: Colors.white,
        onSurface: ZiaOlive.shade400,
        surfaceContainerHighest: ZiaOlive.shade50,
        surfaceContainerHigh: ZiaOlive.shade100,  // 代码块背景
        outline: ZiaOlive.shade100,
        error: ZiaOlive.error,
      ),
      scaffoldBackgroundColor: ZiaOlive.shade50,
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.white,
        foregroundColor: ZiaOlive.shade400,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: ZiaOlive.shade400,
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
      ),
      cardTheme: CardThemeData(
        color: Colors.white,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: ZiaOlive.shade100, width: 0.5),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: ZiaOlive.shade100,
        thickness: 0.5,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: ZiaOlive.shade100),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: ZiaOlive.shade100),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: ZiaOlive.shade500, width: 1.5),
        ),
        hintStyle: const TextStyle(color: ZiaOlive.shade200),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: ZiaOlive.shade500,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: ZiaOlive.shade500,
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: ZiaOlive.shade500,
        foregroundColor: Colors.white,
        elevation: 2,
      ),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: ZiaOlive.shade700,
        contentTextStyle: const TextStyle(color: Colors.white),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    );
  }

  /// 暗色主题
  static ThemeData get dark {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.dark(
        primary: ZiaOlive.shade300,
        onPrimary: ZiaOlive.shade900,
        primaryContainer: ZiaOlive.shade700,
        onPrimaryContainer: ZiaOlive.shade100,
        secondary: ZiaOlive.shade200,
        onSecondary: ZiaOlive.shade900,
        surface: ZiaOlive.shade800,
        onSurface: ZiaOlive.shade100,
        surfaceContainerHighest: ZiaOlive.shade900,
        surfaceContainerHigh: ZiaOlive.shade700,  // 代码块背景
        outline: ZiaOlive.shade700,
        error: ZiaOlive.error,
      ),
      scaffoldBackgroundColor: ZiaOlive.shade900,
      appBarTheme: const AppBarTheme(
        backgroundColor: ZiaOlive.shade800,
        foregroundColor: ZiaOlive.shade100,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: ZiaOlive.shade100,
          fontSize: 18,
          fontWeight: FontWeight.w600,
        ),
      ),
      cardTheme: CardThemeData(
        color: ZiaOlive.shade800,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: ZiaOlive.shade700, width: 0.5),
        ),
      ),
      dividerTheme: const DividerThemeData(
        color: ZiaOlive.shade700,
        thickness: 0.5,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: ZiaOlive.shade800,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: ZiaOlive.shade700),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: ZiaOlive.shade700),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(8),
          borderSide: const BorderSide(color: ZiaOlive.shade300, width: 1.5),
        ),
        hintStyle: const TextStyle(color: ZiaOlive.shade200),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: ZiaOlive.shade500,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: ZiaOlive.shade300,
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: ZiaOlive.shade500,
        foregroundColor: Colors.white,
        elevation: 2,
      ),
      listTileTheme: const ListTileThemeData(
        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: ZiaOlive.shade700,
        contentTextStyle: const TextStyle(color: Colors.white),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
    );
  }
}
