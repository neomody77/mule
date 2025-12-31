package com.claudecode.claude_code_remote

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.util.Log
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    companion object {
        private const val TAG = "MainActivity"
    }

    // 命令通道
    private val COMMAND_CHANNEL = "com.mule/command"
    private val ACTION_EXECUTE = "com.mule.EXECUTE"

    // 旧的 ADB 通道（保持兼容）
    private val LEGACY_CHANNEL = "com.claudecode.claude_code_remote/adb"

    private var commandChannel: MethodChannel? = null
    private var legacyChannel: MethodChannel? = null

    private val commandReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            handleCommandIntent(intent)
        }
    }

    /**
     * 处理来自广播或 Intent 的命令
     */
    private fun handleCommandIntent(intent: Intent?) {
        Log.d(TAG, "handleCommandIntent: action=${intent?.action}")
        Log.d(TAG, "Intent extras: ${intent?.extras}")
        when (intent?.action) {
            // 新的统一命令接口
            ACTION_EXECUTE -> {
                val command = intent.getStringExtra("command")
                Log.d(TAG, "Raw command extra: '$command'")
                if (command == null) {
                    Log.w(TAG, "Command is null")
                    return
                }
                Log.d(TAG, "Execute command: $command")
                commandChannel?.invokeMethod("execute", command)
            }
            // 旧的兼容接口
            "com.claudecode.SEND_MESSAGE" -> {
                val message = intent.getStringExtra("message") ?: return
                legacyChannel?.invokeMethod("sendMessage", message)
            }
            "com.claudecode.TAP_SEND" -> {
                legacyChannel?.invokeMethod("tapSend", null)
            }
            "com.claudecode.SET_TEXT" -> {
                val text = intent.getStringExtra("text") ?: return
                legacyChannel?.invokeMethod("setText", text)
            }
        }
    }

    /**
     * 处理应用已经在前台运行时收到的 Intent（来自 CommandReceiver）
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        Log.d(TAG, "onNewIntent: action=${intent.action}")
        handleCommandIntent(intent)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        // 新的命令通道
        commandChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, COMMAND_CHANNEL)

        // 旧的兼容通道
        legacyChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, LEGACY_CHANNEL)

        // 注册广播接收器
        val filter = IntentFilter().apply {
            // 新的命令
            addAction(ACTION_EXECUTE)
            // 旧的兼容命令
            addAction("com.claudecode.SEND_MESSAGE")
            addAction("com.claudecode.TAP_SEND")
            addAction("com.claudecode.SET_TEXT")
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(commandReceiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(commandReceiver, filter)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(commandReceiver)
    }
}
