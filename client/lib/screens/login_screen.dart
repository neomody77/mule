import 'package:clerk_flutter/clerk_flutter.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../providers/auth_provider.dart';
import '../config/app_config.dart';

/// 登录界面
///
/// 仅在 Clerk 认证模式下使用。
/// 当不使用 Clerk 时，此文件可安全删除。
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  @override
  void initState() {
    super.initState();
    _initClerk();
  }

  Future<void> _initClerk() async {
    final publishableKey = AppConfig.clerkPublishableKey;
    if (publishableKey != null && publishableKey.isNotEmpty) {
      await ref.read(authProvider.notifier).initClerkAuth(publishableKey);
    }
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    // 如果已登录，显示加载中（等待导航）
    if (authState.isAuthenticated) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(),
        ),
      );
    }

    // 显示 Clerk 登录 UI
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Logo 和标题
              const Icon(
                Icons.code,
                size: 80,
                color: Colors.blue,
              ),
              const SizedBox(height: 24),
              Text(
                'Mule',
                style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                  fontWeight: FontWeight.bold,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                'Mobile Remote Coding Platform',
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: Colors.grey[600],
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 48),

              // Clerk 登录组件
              if (authState.isLoading)
                const Center(child: CircularProgressIndicator())
              else if (authState.error != null)
                _buildErrorState(authState.error!)
              else
                _buildClerkSignIn(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildClerkSignIn() {
    // 使用 Clerk 的 SignIn 组件
    return ClerkAuth(
      publishableKey: AppConfig.clerkPublishableKey ?? '',
      child: ClerkSignIn(
        onSignedIn: () {
          // 登录成功后刷新状态
          ref.read(authProvider.notifier).onClerkSignIn();
        },
      ),
    );
  }

  Widget _buildErrorState(String error) {
    return Column(
      children: [
        Icon(
          Icons.error_outline,
          size: 48,
          color: Colors.red[400],
        ),
        const SizedBox(height: 16),
        Text(
          'Authentication Error',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        const SizedBox(height: 8),
        Text(
          error,
          style: TextStyle(color: Colors.grey[600]),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 24),
        ElevatedButton(
          onPressed: _initClerk,
          child: const Text('Retry'),
        ),
      ],
    );
  }
}

/// 用户信息组件（可在设置页面使用）
class ClerkUserProfile extends ConsumerWidget {
  const ClerkUserProfile({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);

    if (!authState.isAuthenticated || authState.mode != AuthMode.clerk) {
      return const SizedBox.shrink();
    }

    return ListTile(
      leading: const CircleAvatar(
        child: Icon(Icons.person),
      ),
      title: Text('User ID: ${authState.userId ?? 'Unknown'}'),
      trailing: IconButton(
        icon: const Icon(Icons.logout),
        onPressed: () async {
          await ref.read(authProvider.notifier).signOut();
        },
      ),
    );
  }
}
