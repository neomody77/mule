import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../services/clerk_auth_service.dart';

/// 认证模式
enum AuthMode {
  /// 静态 Token 认证（默认）
  token,

  /// Clerk 认证
  clerk,
}

/// 认证状态
class AuthState {
  final AuthMode mode;
  final bool isAuthenticated;
  final String? userId;
  final String? token;
  final bool isLoading;
  final String? error;

  const AuthState({
    this.mode = AuthMode.token,
    this.isAuthenticated = false,
    this.userId,
    this.token,
    this.isLoading = false,
    this.error,
  });

  AuthState copyWith({
    AuthMode? mode,
    bool? isAuthenticated,
    String? userId,
    String? token,
    bool? isLoading,
    String? error,
  }) {
    return AuthState(
      mode: mode ?? this.mode,
      isAuthenticated: isAuthenticated ?? this.isAuthenticated,
      userId: userId ?? this.userId,
      token: token ?? this.token,
      isLoading: isLoading ?? this.isLoading,
      error: error,
    );
  }
}

/// 认证 Provider
class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier() : super(const AuthState());

  /// 使用静态 Token 认证
  void useTokenAuth(String token) {
    state = AuthState(
      mode: AuthMode.token,
      isAuthenticated: true,
      token: token,
    );
  }

  /// 初始化 Clerk 认证
  Future<void> initClerkAuth(String publishableKey) async {
    state = state.copyWith(isLoading: true, error: null);

    try {
      await ClerkAuthService.instance.initialize(publishableKey);
      await _refreshClerkState();
    } catch (e) {
      state = state.copyWith(
        isLoading: false,
        error: 'Failed to initialize Clerk: $e',
      );
    }
  }

  /// 刷新 Clerk 认证状态
  Future<void> _refreshClerkState() async {
    final clerkService = ClerkAuthService.instance;

    if (!clerkService.isInitialized) {
      state = state.copyWith(isLoading: false);
      return;
    }

    final isSignedIn = clerkService.isSignedIn;
    String? token;

    if (isSignedIn) {
      token = await clerkService.getSessionToken();
    }

    state = AuthState(
      mode: AuthMode.clerk,
      isAuthenticated: isSignedIn,
      userId: clerkService.userId,
      token: token,
      isLoading: false,
    );
  }

  /// Clerk 登录成功后调用
  Future<void> onClerkSignIn() async {
    await _refreshClerkState();
  }

  /// 登出
  Future<void> signOut() async {
    if (state.mode == AuthMode.clerk) {
      await ClerkAuthService.instance.signOut();
    }

    state = AuthState(mode: state.mode);
  }

  /// 获取当前有效的 Token
  Future<String?> getToken() async {
    if (state.mode == AuthMode.clerk) {
      // Clerk 模式：获取最新的 session token
      return await ClerkAuthService.instance.getSessionToken();
    } else {
      // Token 模式：返回静态 token
      return state.token;
    }
  }
}

/// 全局 Auth Provider
final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier();
});
