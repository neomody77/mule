module.exports = {
  apps: [{
    name: 'mule',
    script: '.venv/bin/uvicorn',
    args: 'app.main:app --host 0.0.0.0 --port 8000',
    cwd: '/home/ubuntu/mule',
    interpreter: 'none',
    env: {
      PATH: '/home/ubuntu/mule/.venv/bin:/usr/local/bin:/usr/bin:/bin'
    },
    // 日志配置
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    error_file: '/home/ubuntu/mule/logs/error.log',
    out_file: '/home/ubuntu/mule/logs/out.log',
    merge_logs: true,
    // 重启策略
    autorestart: true,
    max_restarts: 10,
    restart_delay: 1000,
    // 监控
    watch: false,
  }]
};
