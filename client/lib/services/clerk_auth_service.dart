import 'package:clerk_flutter/clerk_flutter.dart';
import 'package:flutter/foundation.dart';

/// Clerk 认证服务
///
/// 封装 Clerk SDK，提供统一的认证接口。
/// 当不使用 Clerk 时，此文件可安全删除。
class ClerkAuthService {
  static ClerkAuthService? _instance;

  ClerkAuth? _clerkAuth;
  bool _initialized = false;

  ClerkAuthService._();

  static ClerkAuthService get instance {
    _instance ??= ClerkAuthService._();
    return _instance!;
  }

  /// 初始化 Clerk
  ///
  /// [publishableKey] 从 Clerk Dashboard 获取
  Future<void> initialize(String publishableKey) async {
    if (_initialized) return;

    try {
      _clerkAuth = ClerkAuth(publishableKey: publishableKey);
      _initialized = true;
      debugPrint('[ClerkAuthService] Initialized with key: ${publishableKey.substring(0, 20)}...');
    } catch (e) {
      debugPrint('[ClerkAuthService] Failed to initialize: $e');
      rethrow;
    }
  }

  /// 是否已初始化
  bool get isInitialized => _initialized;

  /// 获取 ClerkAuth 实例（用于 UI 组件）
  ClerkAuth? get clerkAuth => _clerkAuth;

  /// 是否已登录
  bool get isSignedIn => _clerkAuth?.user != null;

  /// 当前用户
  User? get currentUser => _clerkAuth?.user;

  /// 当前用户 ID
  String? get userId => _clerkAuth?.user?.id;

  /// 获取 Session Token（用于 API 请求）
  Future<String?> getSessionToken() async {
    if (!_initialized || _clerkAuth == null) {
      return null;
    }

    try {
      final session = _clerkAuth!.session;
      if (session == null) return null;

      // 获取 JWT token
      final token = await session.getToken();
      return token;
    } catch (e) {
      debugPrint('[ClerkAuthService] Failed to get session token: $e');
      return null;
    }
  }

  /// 登出
  Future<void> signOut() async {
    if (!_initialized || _clerkAuth == null) return;

    try {
      await _clerkAuth!.signOut();
      debugPrint('[ClerkAuthService] Signed out');
    } catch (e) {
      debugPrint('[ClerkAuthService] Failed to sign out: $e');
      rethrow;
    }
  }

  /// 销毁实例
  void dispose() {
    _clerkAuth = null;
    _initialized = false;
    _instance = null;
  }
}
