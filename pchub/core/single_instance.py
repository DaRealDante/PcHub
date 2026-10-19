import getpass
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    messageReceived = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            userName = getpass.getuser()
        except Exception:
            userName = "user"
        self.serverName = f"PCHub-{userName}"
        self.server = None

    def sendToPrimary(self, args):
        socket = QLocalSocket()
        socket.connectToServer(self.serverName)
        if not socket.waitForConnected(400):
            return False
        socket.write(json.dumps(args).encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(400)
        socket.disconnectFromServer()
        return True

    def becomePrimary(self):
        QLocalServer.removeServer(self.serverName)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.WorldAccessOption)
        self.server.newConnection.connect(self._handleConnection)
        return self.server.listen(self.serverName)

    def release(self):
        if self.server:
            self.server.close()
            self.server = None

    def _handleConnection(self):
        while self.server and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.waitForReadyRead(400)
            payload = bytes(socket.readAll()).decode("utf-8", errors="ignore")
            try:
                args = json.loads(payload) if payload else []
            except ValueError:
                args = []
            self.messageReceived.emit(args if isinstance(args, list) else [])
            socket.disconnectFromServer()
