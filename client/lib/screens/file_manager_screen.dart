import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../config/theme.dart';
import '../models/file_node.dart';
import '../models/server_config.dart';
import '../services/api_service.dart';
import 'file_viewer_screen.dart';

/// 文件管理器页面
class FileManagerScreen extends ConsumerStatefulWidget {
  final ServerConfig server;
  final String workspaceId;

  const FileManagerScreen({
    super.key,
    required this.server,
    required this.workspaceId,
  });

  @override
  ConsumerState<FileManagerScreen> createState() => _FileManagerScreenState();
}

class _FileManagerScreenState extends ConsumerState<FileManagerScreen> {
  final ApiService _api = ApiService();

  String _currentPath = '';
  List<FileNode> _files = [];
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadFiles();
  }

  Future<void> _loadFiles([String? path]) async {
    setState(() {
      _isLoading = true;
      _error = null;
      if (path != null) {
        _currentPath = path;
      }
    });

    try {
      // 使用 server 的配置调用 API
      final files = await _fetchFiles(_currentPath);
      setState(() {
        _files = files;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<List<FileNode>> _fetchFiles(String path) async {
    final url = '${widget.server.httpBaseUrl}/api/workspaces/${widget.workspaceId}/files';
    final uri = Uri.parse(url).replace(queryParameters: {'path': path});

    final response = await _api.listFilesWithServer(
      widget.server,
      widget.workspaceId,
      path: path,
    );
    return response;
  }

  void _navigateToDirectory(String path) {
    _loadFiles(path);
  }

  void _navigateUp() {
    if (_currentPath.isEmpty) return;

    final parts = _currentPath.split('/');
    parts.removeLast();
    _loadFiles(parts.join('/'));
  }

  void _openFile(FileNode file) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => FileViewerScreen(
          server: widget.server,
          workspaceId: widget.workspaceId,
          filePath: file.path,
          fileName: file.name,
        ),
      ),
    );
  }

  List<String> get _pathParts {
    if (_currentPath.isEmpty) return [];
    return _currentPath.split('/');
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Files'),
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: Column(
        children: [
          // 面包屑导航
          _buildBreadcrumb(),

          // 文件列表
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? _buildError()
                    : _files.isEmpty
                        ? _buildEmpty()
                        : _buildFileList(),
          ),
        ],
      ),
    );
  }

  Widget _buildBreadcrumb() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? ZiaOlive.shade800 : ZiaOlive.shade50;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      color: bgColor,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            // 根目录
            InkWell(
              onTap: () => _loadFiles(''),
              borderRadius: BorderRadius.circular(4),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.home, size: 18, color: ZiaOlive.shade500),
                    const SizedBox(width: 4),
                    Text(
                      widget.workspaceId,
                      style: TextStyle(
                        color: ZiaOlive.shade500,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // 路径部分
            ..._pathParts.asMap().entries.map((entry) {
              final index = entry.key;
              final part = entry.value;
              final isLast = index == _pathParts.length - 1;
              final pathToHere = _pathParts.sublist(0, index + 1).join('/');

              return Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.chevron_right, size: 18, color: ZiaOlive.shade300),
                  InkWell(
                    onTap: isLast ? null : () => _loadFiles(pathToHere),
                    borderRadius: BorderRadius.circular(4),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      child: Text(
                        part,
                        style: TextStyle(
                          color: isLast ? null : ZiaOlive.shade500,
                          fontWeight: isLast ? FontWeight.w600 : FontWeight.w500,
                        ),
                      ),
                    ),
                  ),
                ],
              );
            }),
          ],
        ),
      ),
    );
  }

  Widget _buildError() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.error_outline, size: 48, color: ZiaOlive.error),
          const SizedBox(height: 16),
          Text(
            'Failed to load files',
            style: TextStyle(
              fontSize: 16,
              color: ZiaOlive.error,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _error ?? '',
            style: TextStyle(
              fontSize: 12,
              color: ZiaOlive.shade300,
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: () => _loadFiles(_currentPath),
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildEmpty() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.folder_open, size: 48, color: ZiaOlive.shade300),
          const SizedBox(height: 16),
          Text(
            'No files',
            style: TextStyle(
              fontSize: 16,
              color: ZiaOlive.shade300,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFileList() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final dividerColor = isDark ? ZiaOlive.shade700 : ZiaOlive.shade100;

    // 排序：目录在前，文件在后，各自按名称排序
    final sortedFiles = List<FileNode>.from(_files)
      ..sort((a, b) {
        if (a.isDirectory && !b.isDirectory) return -1;
        if (!a.isDirectory && b.isDirectory) return 1;
        return a.name.toLowerCase().compareTo(b.name.toLowerCase());
      });

    return RefreshIndicator(
      onRefresh: () => _loadFiles(_currentPath),
      child: ListView.separated(
        itemCount: sortedFiles.length,
        separatorBuilder: (_, __) => Divider(height: 1, color: dividerColor),
        itemBuilder: (context, index) {
          final file = sortedFiles[index];
          return _buildFileItem(file);
        },
      ),
    );
  }

  Widget _buildFileItem(FileNode file) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return ListTile(
      leading: Icon(
        file.isDirectory ? Icons.folder : _getFileIcon(file.name),
        color: file.isDirectory ? ZiaOlive.shade500 : ZiaOlive.shade400,
      ),
      title: Text(
        file.name,
        style: const TextStyle(fontSize: 15),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: file.isDirectory
          ? null
          : Text(
              _formatFileInfo(file),
              style: TextStyle(
                fontSize: 12,
                color: ZiaOlive.shade300,
              ),
            ),
      trailing: file.isDirectory
          ? Icon(Icons.chevron_right, color: ZiaOlive.shade300)
          : null,
      onTap: () {
        if (file.isDirectory) {
          _navigateToDirectory(file.path);
        } else {
          _openFile(file);
        }
      },
    );
  }

  IconData _getFileIcon(String fileName) {
    final ext = fileName.split('.').last.toLowerCase();
    switch (ext) {
      case 'dart':
      case 'py':
      case 'js':
      case 'ts':
      case 'java':
      case 'kt':
      case 'swift':
      case 'go':
      case 'rs':
      case 'c':
      case 'cpp':
      case 'h':
        return Icons.code;
      case 'json':
      case 'yaml':
      case 'yml':
      case 'toml':
      case 'xml':
        return Icons.data_object;
      case 'md':
      case 'txt':
      case 'readme':
        return Icons.description;
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'gif':
      case 'svg':
      case 'webp':
        return Icons.image;
      case 'pdf':
        return Icons.picture_as_pdf;
      case 'zip':
      case 'tar':
      case 'gz':
      case 'rar':
        return Icons.archive;
      default:
        return Icons.insert_drive_file;
    }
  }

  String _formatFileInfo(FileNode file) {
    final parts = <String>[];

    if (file.size != null) {
      parts.add(_formatFileSize(file.size!));
    }

    if (file.modified != null) {
      parts.add(DateFormat('MMM d, yyyy').format(file.modified!));
    }

    return parts.join(' • ');
  }

  String _formatFileSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    }
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }
}
