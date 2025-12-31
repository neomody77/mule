/// 文件节点类型
enum FileNodeType {
  file,
  directory,
}

/// 文件节点
class FileNode {
  final String name;
  final String path;
  final FileNodeType type;
  final int? size;
  final DateTime? modified;
  final List<FileNode> children;
  final bool isExpanded;

  FileNode({
    required this.name,
    required this.path,
    required this.type,
    this.size,
    this.modified,
    this.children = const [],
    this.isExpanded = false,
  });

  bool get isDirectory => type == FileNodeType.directory;
  bool get isFile => type == FileNodeType.file;

  factory FileNode.fromJson(Map<String, dynamic> json) {
    return FileNode(
      name: json['name'] as String,
      path: json['path'] as String,
      type: json['type'] == 'directory'
          ? FileNodeType.directory
          : FileNodeType.file,
      size: json['size'] as int?,
      modified: json['modified'] != null
          ? DateTime.parse(json['modified'] as String)
          : null,
    );
  }

  FileNode copyWith({
    String? name,
    String? path,
    FileNodeType? type,
    int? size,
    DateTime? modified,
    List<FileNode>? children,
    bool? isExpanded,
  }) {
    return FileNode(
      name: name ?? this.name,
      path: path ?? this.path,
      type: type ?? this.type,
      size: size ?? this.size,
      modified: modified ?? this.modified,
      children: children ?? this.children,
      isExpanded: isExpanded ?? this.isExpanded,
    );
  }
}
