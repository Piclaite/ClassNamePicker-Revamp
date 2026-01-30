# SingleInstanceManager.py
from PyQt5.QtCore import QObject, pyqtSignal, QByteArray
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

class SingleInstanceManager(QObject):
    """单实例管理器：确保只有一个程序实例运行"""
    show_window_signal = pyqtSignal()
    
    def __init__(self, app_name="ClassNamePicker"):
        super().__init__()
        self.app_name = app_name
        self.server = None
        
    def check_existing(self) -> bool:
        """
        检测是否已有实例在运行
        返回: True=已有实例(已发送激活命令), False=没有实例
        """
        socket = QLocalSocket()
        socket.connectToServer(self.app_name)
        
        if socket.waitForConnected(500):
            print(f"[SINGLE] 检测到已有实例，发送激活请求...")
            socket.write(QByteArray(b"SHOW_WINDOW"))
            socket.flush()
            socket.waitForBytesWritten(1000)
            socket.disconnectFromServer()
            return True
        
        print(f"[SINGLE] 未检测到现有实例...")
        return False
    
    def start_server(self):
        """启动本地服务器（必须在信号连接完成后调用）"""
        print(f"[SINGLE] 创建服务器...")
        self.server = QLocalServer()
        self.server.newConnection.connect(self._on_new_connection)
        
        # 清理残留
        if self.server.serverName() and self.server.serverName() in QLocalServer.servers():
            QLocalServer.removeServer(self.app_name)
        
        if not self.server.listen(self.app_name):
            print(f"[SINGLE] 无法创建服务器: {self.server.errorString()}")
            return False
        
        print(f"[SINGLE] 服务器已启动，监听: {self.app_name}")
        return True
        
    def _on_new_connection(self):
        """处理来自其他实例的连接请求"""
        socket = self.server.nextPendingConnection()
        if not socket:
            return
        
        if socket.waitForReadyRead(1000):
            data = socket.readAll().data().decode('utf-8').strip()
            print(f"[SINGLE] 收到其他实例命令: {data}")
            
            if data == "SHOW_WINDOW":
                # 发射信号，让主窗口处理
                self.show_window_signal.emit()
        
        socket.disconnectFromServer()
        socket.deleteLater()
    
    def cleanup(self):
        """清理资源：关闭服务器"""
        if self.server:
            self.server.close()
            print("[SINGLE] 服务器已关闭")