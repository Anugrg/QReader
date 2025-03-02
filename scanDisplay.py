import sys
import os
import time
import base64
import multiprocessing as mp
import logging
from threading import Thread
from datetime import datetime as dt
import socket


from PySide6.QtWidgets import (QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QDateEdit)
from PySide6.QtCore import  QObject, Signal, Slot, QByteArray, QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtGui import QPixmap, QColor, QBrush


import readScanner as scanner


# create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

file_handler = logging.FileHandler("gui.log", mode="a", encoding="utf-8")

formatter = logging.Formatter(
    "{asctime} - {levelname} - {message}",
    style="{",
    datefmt="%Y-%m-%d %H:%M",
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class TcpSignals(QObject):
    result = Signal(tuple)
    fail = Signal(tuple)
    conn = Signal(int)


class Communicator(QObject):
    data_received = Signal(list)


class TCPWorker(QRunnable):
    '''
    Worker thread
    '''

    def __init__(self, qty : int, host, port, row):
        super().__init__()
        self.data = qty
        self.host = host
        self.port = port
        self.signal = TcpSignals()
        self.recv_bytes = 4096
        self.row = row

    @Slot()  # QtCore.Slot
    def run(self):

        logger.info(f'Sending to PLC --- {dt.now()}')
        success = True
        retry  = 1
        while retry > 0:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((self.host, self.port))
                    logger.info(f'Sending  {self.data} to plc')

                    s.sendall(self.data.to_bytes(2, 'big'))
                    resp = s.recv(self.recv_bytes)
                    logger.info(f'Reply from TCP server: {resp}')
                    success = True
                    retry = 0
            except ConnectionRefusedError:
                logger.error("TCP connection refused", exc_info=True)
                self.signal.conn.emit(0)
                time.sleep(1)
                success = False
                retry -= 1
            except AttributeError:
                logger.error(f'Data is not int : {self.data}', exc_info=True)
                time.sleep(1)
                retry = -1
                success = False

        # emit signal to change PLC success status
        # if it got here then resp is received
        # so emit signal for PLC tcp status as well again
        if success:
            self.signal.conn.emit(1)
            result = int.from_bytes(resp, 'big')
            if result:
                self.signal.result.emit((result, self.row))
            else:
                self.signal.fail.emit((result, self.row))


class TableApp(QWidget):

    def __init__(self, pipe):
        super().__init__()
        logger.info("Table rendered...")
        logger.info(pipe)
        self.pipe = pipe
        self.initUI()
        logger.info("Setting up Signal...")
        

        # thread to fetch data from pipe
        self.communicator = Communicator()
        self.communicator.data_received.connect(self.add_row)
        self.t = Thread(target=self.read_from_pipe)
        self.t.daemon = True
        self.t.start()

        self.threadpool = QThreadPool()


    def initUI(self):
        self.setWindowTitle('Barcode Scanner Reader Display')
        self.setGeometry(100, 100, 2200, 800)
        layout = QVBoxLayout()
        plc_layout = QHBoxLayout()

        self.plc_tcp_status = QLabel("PLC:")
        self.plc_tcp_status.setFixedWidth(50)

        self.plc_tcp_status_text = QLineEdit("Waiting")
        self.plc_tcp_status_text.setReadOnly(True)
        self.plc_tcp_status_text.setFixedWidth(80)

        self.chk_conn_button = QPushButton('Check', self)
        self.chk_conn_button.clicked.connect(self.check_tcp_status)

        plc_layout.addWidget(self.plc_tcp_status)
        plc_layout.addWidget(self.plc_tcp_status_text)
        plc_layout.addWidget(self.chk_conn_button)
        plc_layout.setSpacing(0)
        plc_layout.setContentsMargins(5, 5, 5, 5)
        plc_layout.setAlignment(self.plc_tcp_status, Qt.AlignLeft)
        plc_layout.setAlignment(self.plc_tcp_status_text, Qt.AlignLeft)
        plc_layout.addStretch()

        # Input layout
        input_layout = QHBoxLayout()
        self.date_field = QLineEdit()
        self.date_field.setText(dt.today().strftime('%Y-%m-%d'))
        self.date_field.setReadOnly(True)
        self.name_field = QLineEdit(self)
        self.name_field.setMinimumWidth(350)
        self.label = QLabel("Lot no.")
        self.name_field.setPlaceholderText('Lot no.')

        input_layout.addWidget(self.date_field)
        input_layout.addWidget(self.label)
        input_layout.addWidget(self.name_field)
        self.start_button = QPushButton('Start', self)
        self.start_button.clicked.connect(self.send_tcp)
        input_layout.addWidget(self.start_button)

        self.success_color = QColor(200, 255, 200)
        self.fail_color = QColor(255, 200, 200)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['Model', 'Packing Code', 'Quantity', 'PLC'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        # Clear button
        self.clear_button = QPushButton('Clear', self)
        self.clear_button.clicked.connect(self.clear_table)
 
        layout.addLayout(plc_layout)
        layout.addLayout(input_layout)
        layout.addWidget(self.table)
        layout.addWidget(self.clear_button)
        self.check_tcp_status()
        self.setLayout(layout)

    def check_tcp_status(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('127.0.0.1', 65432))
                logger.info(s.getpeername())
                self.plc_tcp_status_text.setText('CONNECTED')

        except ConnectionRefusedError:
            self.plc_tcp_status_text.setText('FAILED')
            logger.error("TCP connection refused", exc_info=True)


    def toggle_tcp_conn(self, status):

        if status:
            self.plc_tcp_status_text.setText('CONNECTED')
        else:
            self.plc_tcp_status_text.setText('FAILED')


    def read_from_pipe(self):
        while True:
            if self.pipe.poll():
                data = self.pipe.recv()
                logger.info(data)
                self.communicator.data_received.emit(data)


    def send_tcp(self):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 3).text() == 'SUCCESS':
                continue

            qty = self.table.item(row, 2).text()
            worker = TCPWorker(int(qty), '127.0.0.1', 65432, row)
            worker.signal.result.connect(self.get_plc_status)
            worker.signal.fail.connect(self.get_plc_status)
            worker.signal.conn.connect(self.toggle_tcp_conn)
            self.threadpool.start(worker)

    def get_plc_status(self, result):
        status, row = result
        logger.info(f"Sent to plc success: {status}")
        if status:
            self.table.setItem(row, 3, QTableWidgetItem('SUCCESS'))
            self.table.item(row, 3).setBackground(QBrush(self.success_color))
        else:
            self.table.setItem(row, 3, QTableWidgetItem('FAIL'))
            self.table.item(row, 3).setBackground(QBrush(self.fail_color))



    @Slot(list)
    def add_row(self, data):
        logger.info(f"Data received: {data}")
        if data and len(data) == 3:
            model, packing_code, quantity = data
            row_position = self.table.rowCount()
            self.table.insertRow(row_position)
            self.table.setItem(row_position, 0, QTableWidgetItem(model))
            self.table.setItem(row_position, 1, QTableWidgetItem(packing_code))
            self.table.setItem(row_position, 2, QTableWidgetItem(quantity))
            self.table.setItem(row_position, 3, QTableWidgetItem('Idle'))
            # self.send_tcp(int(data[-1])) 

        else:
            self.name_field.clear()
            self.name_field.setText(data[0])


    def clear_table(self):
        self.table.setRowCount(0)


class MainWindow(QMainWindow):
    def __init__(self, pipe):
        super().__init__()
        logger.info("Main window created...")
        self.setFixedHeight(650)
        self.table = TableApp(pipe)
        self.setCentralWidget(self.table)



if __name__ == '__main__':

    if sys.platform.startswith('win'):
        # On Windows calling this function is necessary.
        mp.freeze_support()

    base64_img = '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'
    image_data = base64.b64decode(base64_img)
    app = QApplication(sys.argv)
    parent_conn, child_conn = mp.Pipe()
    logging.info("Starting process for scanner...")

    p = mp.Process(target=scanner.start, args=(child_conn,))
    p.daemon = True
    p.start()
    logging.info("Main window rendering")

    window = MainWindow(parent_conn)
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(image_data))

    window.setWindowIcon(pixmap)
    window.setWindowTitle("Barcode Scanner Display")

    window.show()
    sys.exit(app.exec())
    logging.info("Terminating process for scanner...")
    p.terminate()
    p.join()
