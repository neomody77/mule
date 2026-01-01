/// 工作区模型（完整版，用于详细视图）
class Workspace {
  final String id;
  final String name;
  final String? description;
  final DateTime createdAt;
  final DateTime updatedAt;
  final String path;
  final bool deleted;
  final DateTime? deletedAt;

  Workspace({
    required this.id,
    required this.name,
    this.description,
    required this.createdAt,
    required this.updatedAt,
    required this.path,
    this.deleted = false,
    this.deletedAt,
  });

  factory Workspace.fromJson(Map<String, dynamic> json) {
    return Workspace(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      path: json['path'] as String,
      deleted: json['deleted'] as bool? ?? false,
      deletedAt: json['deleted_at'] != null
          ? DateTime.parse(json['deleted_at'] as String)
          : null,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'description': description,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt.toIso8601String(),
      'path': path,
      'deleted': deleted,
      'deleted_at': deletedAt?.toIso8601String(),
    };
  }
}

/// 工作区信息（简化版，用于列表展示）
class WorkspaceInfo {
  final String id;
  final String name;
  final String? description;
  final String path;
  final bool deleted;

  WorkspaceInfo({
    required this.id,
    required this.name,
    this.description,
    required this.path,
    this.deleted = false,
  });

  factory WorkspaceInfo.fromJson(Map<String, dynamic> json) {
    return WorkspaceInfo(
      id: json['id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      path: json['path'] as String,
      deleted: json['deleted'] as bool? ?? false,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'description': description,
      'path': path,
      'deleted': deleted,
    };
  }
}
