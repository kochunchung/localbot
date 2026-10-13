import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import '../models/message.dart';

/// Local SQLite database service for offline message storage and caching.
class DatabaseService {
  static final DatabaseService _instance = DatabaseService._internal();
  factory DatabaseService() => _instance;
  DatabaseService._internal();

  Database? _db;

  Future<Database> get database async {
    if (_db != null) return _db!;
    _db = await _initDatabase();
    return _db!;
  }

  Future<Database> _initDatabase() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'localbot_chat.db');

    return await openDatabase(
      path,
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            is_user INTEGER,
            message_type TEXT,
            content TEXT,
            timestamp INTEGER,
            status TEXT
          )
        ''');
        await db.execute('CREATE INDEX idx_timestamp ON messages(timestamp)');
      },
    );
  }

  Future<void> saveMessage(ChatMessage message) async {
    final db = await database;
    await db.insert(
      'messages',
      message.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<List<ChatMessage>> getMessages({int limit = 100, int offset = 0}) async {
    final db = await database;
    final List<Map<String, dynamic>> maps = await db.query(
      'messages',
      orderBy: 'timestamp ASC',
      limit: limit,
      offset: offset,
    );

    return List.generate(maps.length, (i) => ChatMessage.fromMap(maps[i]));
  }

  Future<void> updateMessageStatus(String id, String status) async {
    final db = await database;
    await db.update(
      'messages',
      {'status': status},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<void> clearAll() async {
    final db = await database;
    await db.delete('messages');
  }
}
