import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import '../models/message.dart';

/// Local SQLite database service for offline message storage and caching.
///
/// v2（多 Bot）：每則訊息多了 bot_id。舊版（v1）沒有 bot_id，升級時直接清空重建，
/// 需要的話可以用聊天室右上角的「同步」從伺服器補回。
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

  static Future<void> _createSchema(Database db) async {
    await db.execute('''
      CREATE TABLE messages (
        id TEXT NOT NULL,
        bot_id TEXT NOT NULL,
        user_id TEXT,
        is_user INTEGER,
        message_type TEXT,
        content TEXT,
        timestamp INTEGER,
        status TEXT,
        PRIMARY KEY (bot_id, id)
      )
    ''');
    await db.execute('CREATE INDEX idx_bot_timestamp ON messages(bot_id, timestamp)');
  }

  Future<Database> _initDatabase() async {
    final dbPath = await getDatabasesPath();
    final path = join(dbPath, 'localbot_chat.db');

    return await openDatabase(
      path,
      version: 2,
      onCreate: (db, version) => _createSchema(db),
      onUpgrade: (db, oldVersion, newVersion) async {
        await db.execute('DROP TABLE IF EXISTS messages');
        await _createSchema(db);
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

  /// 取得某個 Bot 聊天室最新的 [limit] 則訊息（由舊到新排列）。
  Future<List<ChatMessage>> getMessages(String botId, {int limit = 100}) async {
    final db = await database;
    final List<Map<String, dynamic>> maps = await db.query(
      'messages',
      where: 'bot_id = ?',
      whereArgs: [botId],
      orderBy: 'timestamp DESC',
      limit: limit,
    );
    return maps.reversed.map(ChatMessage.fromMap).toList();
  }

  Future<ChatMessage?> getLastMessage(String botId) async {
    final db = await database;
    final maps = await db.query(
      'messages',
      where: 'bot_id = ?',
      whereArgs: [botId],
      orderBy: 'timestamp DESC',
      limit: 1,
    );
    return maps.isEmpty ? null : ChatMessage.fromMap(maps.first);
  }

  Future<void> updateMessageStatus(String botId, String id, String status) async {
    final db = await database;
    await db.update(
      'messages',
      {'status': status},
      where: 'bot_id = ? AND id = ?',
      whereArgs: [botId, id],
    );
  }

  Future<void> deleteMessage(String botId, String id) async {
    final db = await database;
    await db.delete('messages', where: 'bot_id = ? AND id = ?', whereArgs: [botId, id]);
  }

  /// 清除某個 Bot 的本機紀錄；[botId] 為 null 時清除全部。
  Future<void> clear({String? botId}) async {
    final db = await database;
    if (botId == null) {
      await db.delete('messages');
    } else {
      await db.delete('messages', where: 'bot_id = ?', whereArgs: [botId]);
    }
  }
}
