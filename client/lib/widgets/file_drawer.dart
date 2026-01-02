import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../config/theme.dart';
import '../models/file_node.dart';
import '../models/server_config.dart';
import '../services/api_service.dart';
import '../screens/file_viewer_screen.dart';

/// 文件树抽屉组件
class FileDrawer extends StatefulWidget {
  final ServerConfig server;
  final String workspaceId;

  const FileDrawer({
    super.key,
    required this.server,
    required this.workspaceId,
  });

  @override
  State<FileDrawer> createState() => _FileDrawerState();
}

class _FileDrawerState extends State<FileDrawer> {
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
      final files = await _api.listFilesWithServer(
        widget.server,
        widget.workspaceId,
        path: _currentPath,
      );
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
    final width = MediaQuery.of(context).size.width * 0.85;

    return Drawer(
      width: width > 360 ? 360 : width,
      child: Column(
        children: [
          // 标题栏
          _buildHeader(),

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

  Widget _buildHeader() {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Container(
      padding: EdgeInsets.only(
        top: MediaQuery.of(context).padding.top + 8,
        left: 16,
        right: 8,
        bottom: 8,
      ),
      decoration: BoxDecoration(
        color: isDark ? ZiaOlive.shade800 : ZiaOlive.shade100,
        border: Border(
          bottom: BorderSide(
            color: isDark ? ZiaOlive.shade700 : ZiaOlive.shade200,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(Icons.folder_outlined, color: ZiaOlive.shade500),
          const SizedBox(width: 8),
          const Expanded(
            child: Text(
              'Files',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, size: 20),
            onPressed: () => _loadFiles(_currentPath),
            tooltip: 'Refresh',
          ),
          IconButton(
            icon: const Icon(Icons.close, size: 20),
            onPressed: () => Navigator.pop(context),
            tooltip: 'Close',
          ),
        ],
      ),
    );
  }

  Widget _buildBreadcrumb() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? ZiaOlive.shade900 : ZiaOlive.shade50;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
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
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.home, size: 16, color: ZiaOlive.shade500),
                    const SizedBox(width: 4),
                    Text(
                      'root',
                      style: TextStyle(
                        fontSize: 12,
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
                  Icon(Icons.chevron_right, size: 16, color: ZiaOlive.shade300),
                  InkWell(
                    onTap: isLast ? null : () => _loadFiles(pathToHere),
                    borderRadius: BorderRadius.circular(4),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                      child: Text(
                        part,
                        style: TextStyle(
                          fontSize: 12,
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
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.error_outline, size: 40, color: ZiaOlive.error),
            const SizedBox(height: 12),
            Text(
              'Failed to load',
              style: TextStyle(color: ZiaOlive.error),
            ),
            const SizedBox(height: 8),
            Text(
              _error ?? '',
              style: TextStyle(fontSize: 11, color: ZiaOlive.shade300),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 12),
            TextButton.icon(
              onPressed: () => _loadFiles(_currentPath),
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmpty() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.folder_open, size: 40, color: ZiaOlive.shade300),
          const SizedBox(height: 12),
          Text(
            'Empty folder',
            style: TextStyle(color: ZiaOlive.shade300),
          ),
        ],
      ),
    );
  }

  Widget _buildFileList() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final dividerColor = isDark ? ZiaOlive.shade700 : ZiaOlive.shade100;

    // 排序：目录在前，文件在后
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
    return ListTile(
      dense: true,
      leading: Icon(
        file.isDirectory ? Icons.folder : _getFileIcon(file.name),
        size: 20,
        color: file.isDirectory ? ZiaOlive.shade500 : ZiaOlive.shade400,
      ),
      title: Text(
        file.name,
        style: const TextStyle(fontSize: 14),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: file.isDirectory
          ? null
          : Text(
              _formatFileInfo(file),
              style: TextStyle(fontSize: 11, color: ZiaOlive.shade300),
            ),
      trailing: file.isDirectory
          ? Icon(Icons.chevron_right, size: 18, color: ZiaOlive.shade300)
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
        return Icons.description;
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'gif':
      case 'svg':
        return Icons.image;
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
      parts.add(DateFormat('MMM d').format(file.modified!));
    }
    return parts.join(' · ');
  }

  String _formatFileSize(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
