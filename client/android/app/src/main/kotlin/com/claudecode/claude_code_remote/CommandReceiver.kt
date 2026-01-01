package com.claudecode.claude_code_remote

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * 静态广播接收器 - 用于接收 ADB 广播命令
 * 通过 Intent 启动 MainActivity 并传递命令
 */
class CommandReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "CommandReceiver"
    }

    override fun onReceive(context: Context?, intent: Intent?) {
        if (context == null || intent == null) return

        Log.d(TAG, "Received broadcast: ${intent.action}")

        // 创建启动 MainActivity 的 Intent，携带原始广播数据
        val launchIntent = Intent(context, MainActivity::class.java).apply {
            action = intent.action
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP

            // 复制所有 extras
            intent.extras?.let { putExtras(it) }
        }

        context.startActivity(launchIntent)
    }
}
