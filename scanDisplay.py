import sys
import os
import time
import json
import base64
import multiprocessing as mp
import logging
from threading import Thread
from datetime import datetime as dt
import socket


from PySide6.QtWidgets import (QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QDateEdit)
from PySide6.QtCore import  QObject, Signal, Slot, QByteArray, QRunnable, QThreadPool, QTimer, Qt
from PySide6.QtGui import QPixmap, QColor, QBrush, QMovie


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

    def __init__(self, pipe, config):
        super().__init__()
        logger.info("Table rendered...")
        logger.info(pipe)
        self.pipe = pipe
        self.infeed = False
        self.outfeed = False
        self.tcp_ip = config.get('PLC_TCP_IP')
        self.tcp_port = config.get('PLC_TCP_PORT')
        self.scanner_infeed = config.get('INFEED')
        self.scanner_outfeed = config.get('OUTFEED')
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

        self.plc_tcp_status = QLabel("PLC Connection:")
        self.plc_tcp_status.setFixedWidth(50)
        # Set padding (left, top, right, bottom)
        self.plc_tcp_status.setContentsMargins(80, 10, 20, 10)

        self.plc_tcp_status_text = QLineEdit("Waiting")
        self.plc_tcp_status_text.setReadOnly(True)
        self.plc_tcp_status_text.setFixedWidth(80)

        self.date_label = QLabel("Date")
        self.date_label.setFixedWidth(50)

        self.date_field = QLineEdit()
        self.date_field.setText(dt.today().strftime('%Y-%m-%d'))
        self.date_field.setStyleSheet("background-color: lightgrey;color:white")
        self.date_field.setReadOnly(True)

        self.chk_conn_button = QPushButton('Check', self)
        self.chk_conn_button.clicked.connect(self.check_tcp_status)

        plc_layout.addWidget(self.date_label)
        plc_layout.addWidget(self.date_field)
        plc_layout.addWidget(self.plc_tcp_status)
        plc_layout.addWidget(self.plc_tcp_status_text)
        plc_layout.addWidget(self.chk_conn_button)
        
        plc_layout.setSpacing(5)
        plc_layout.setAlignment(self.plc_tcp_status_text, Qt.AlignLeft)
        plc_layout.addStretch()

        # Input layout
        input_layout = QHBoxLayout()

        self.name_field = QLineEdit(self)
        self.name_field.setPlaceholderText('Lot no.')
        self.name_field.setMinimumWidth(350)

        self.label = QLabel("Lot no.")

        input_layout.addWidget(self.label)
        input_layout.addWidget(self.name_field)

        self.infeed_button = QPushButton('Send to PLC', self)
        self.infeed_button.clicked.connect(self.send_to_plc)
        input_layout.addWidget(self.infeed_button)

        self.success_color = QColor(200, 255, 200)
        self.fail_color = QColor(255, 200, 200)

        # feed process
        feed_status_layout = QHBoxLayout()
        self.infeed_label = QLabel("Infeed")
        self.infeed_field = QLineEdit(self)
        self.infeed_field.setPlaceholderText('Idle')
        self.infeed_field.setStyleSheet("background-color: lightgrey;color:white")
        self.infeed_field.setReadOnly(True)

        self.set_infeed_btn = QPushButton('Set infeed', self)
        self.set_infeed_btn.clicked.connect(self.set_in_status)

        feed_status_layout.addWidget(self.infeed_label)
        feed_status_layout.addWidget(self.infeed_field)
        feed_status_layout.addWidget(self.set_infeed_btn)


        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Model', 'Packing Code', 'Quantity', 'PLC Infeed', 'PLC Outfeed'])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        self.loading_label = QLabel(self)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_movie = QMovie("loading.gif")
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.setStyleSheet("background: transparent;")
        self.loading_label.setVisible(False)

        # Clear button
        self.clear_button = QPushButton('Clear', self)
        self.clear_button.clicked.connect(self.clear_table)

        self.save_table_btn = QPushButton('Save', self)
        self.save_table_btn.clicked.connect(self.save_table)

        layout.addLayout(plc_layout)
        layout.addLayout(input_layout)
        layout.addLayout(feed_status_layout)
        layout.addWidget(self.table)
        layout.addWidget(self.save_table_btn)
        layout.addWidget(self.clear_button)

        self.setLayout(layout)
        
        self.check_tcp_status()


    def start_load(self):
        self.loading_label.setVisible(True)
        self.loading_movie.start()
        self.loading_label.setGeometry(self.table.geometry())
        # Simulate a long-running action
        # QTimer.singleShot(4000, self.stop_load)

    def stop_load(self):
        self.loading_movie.stop()
        self.loading_label.setVisible(False)

    def reset_style(self, widget, text):
        widget.setText(text)
        widget.setStyleSheet("background-color: lightgrey;color:white")


    def check_tcp_status(self):

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self.tcp_ip, self.tcp_port))
                logger.info(s.getpeername())
                self.plc_tcp_status_text.setText('CONNECTED')
                self.plc_tcp_status_text.setStyleSheet("background-color: green;color:white")

        except ConnectionRefusedError:
            self.plc_tcp_status_text.setText('FAILED')
            self.plc_tcp_status_text.setStyleSheet("background-color: red;color:white")
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


    def send_to_plc(self):
        '''
        Sends qty to PLC via TCP
        '''

        if not self.infeed:  # if outfeed is false it means
            for row in range(self.table.rowCount()):
                if self.table.item(row, 3).text() == 'OK':
                    continue

                qty = self.table.item(row, 2).text()
                self.send_tcp(row, qty)


    def send_tcp(self, row, data):
        '''
        Func to transfer to PLC
        '''

        try:
            worker = TCPWorker(int(data), self.tcp_ip, self.tcp_port, row)
            worker.signal.result.connect(self.get_plc_status)
            worker.signal.fail.connect(self.get_plc_status)
            worker.signal.conn.connect(self.toggle_tcp_conn)
            self.threadpool.start(worker)
        except:
            logging.error("Worker failed", exc_info=True)


    def set_in_status(self):

        if self.infeed:
            self.infeed = False
            self.reset_style(self.infeed_field, 'Idle')
        else:

            num_data = self.table.rowCount()

            if num_data > 0:
                count = 0
                for row in range(self.table.rowCount()):
                    if self.table.item(row, 3).text() == 'OK':
                        count += 1

                if count == num_data and not self.outfeed:

                    self.infeed = True
                    self.infeed_field.setText(f"Scanned {count} QR")
                    self.infeed_field.setStyleSheet("background-color: green;color:white")


    def get_plc_status(self, result):
        col = 3
        if self.infeed:
            col = 4
        status, row = result
        logger.info(f"Sent to plc success: {status}")
        if status:
            self.table.setItem(row, col, QTableWidgetItem('OK'))
            self.table.item(row, col).setBackground(QBrush(self.success_color))
        else:
            self.table.setItem(row, col, QTableWidgetItem('FAIL'))
            self.table.item(row, col).setBackground(QBrush(self.fail_color))


    def get_row_by_column_value(self, column, model) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, column)
            if item and item.text() == model:
                return row, self.table.item(row, 2).text()


    def check_row_exists(self, column, model):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, column)
            if item and item.text() == model:
                return True
    
        return False


    def check_outfeed(self, data : list):
        '''
        After infeed, rows are set
        At outfeed, check if scanned QR matches
        by sending qty again to PLC
        '''
        try:
            row_indx, qty = self.get_row_by_column_value(0, data[0])

            self.send_tcp(row_indx, qty)
        except TypeError as e:
            logging.ERROR("Row is not present")


    @Slot(list)
    def add_row(self, data : list):
        logger.info(f"Data received: {data}")

        if data and len(data) == 4:
            model, packing_code, quantity, COM = data

            if COM==self.scanner_outfeed and self.infeed:
                self.check_outfeed(data)

            elif COM==self.scanner_infeed and not self.infeed:
                exists = self.check_row_exists(0, model)
                if not exists:
                    row_position = self.table.rowCount()
                    self.table.insertRow(row_position)
                    self.table.setItem(row_position, 0, QTableWidgetItem(model))
                    self.table.setItem(row_position, 1, QTableWidgetItem(packing_code))
                    self.table.setItem(row_position, 2, QTableWidgetItem(quantity))
                    self.table.setItem(row_position, 3, QTableWidgetItem('Idle'))
                    self.table.setItem(row_position, 4, QTableWidgetItem('Idle'))

        else:
            self.name_field.clear()
            self.name_field.setText(data[0])


    def save_table(self):
        _date = dt.today().strftime('%Y_%m_%d')
        dest_folders = os.path.join(os.getcwd(), _date)
        if self.table.rowCount() > 0:
            data = []
            data_header = ['Model', 'Packing code', 'Quantity']
            for row in range(self.table.rowCount()):
                data.append([self.table.item(row, 0).text(), self.table.item(row, 1).text(), self.table.item(row, 2).text()])

            scanner.create_dir(dest_folders)
            scanner.create_excel(data, data_header, dest_folders, 'MRE_QR_kanban_info.xlsx')

        if bool(self.name_field.text()):
            scanner.save_to_disk(self.name_field.text(), dest_folders)


    def clear_table(self):
        self.table.setRowCount(0)
        self.name_field.clear()
        self.outfeed, self.infeed = False, False
        self.reset_style(self.infeed_field, 'Idle')


class MainWindow(QMainWindow):
    def __init__(self, pipe, config):
        super().__init__()
        logger.info("Main window created...")
        self.setFixedHeight(650)

        self.table = TableApp(pipe, config)
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

    with open('config.json', 'r') as f:
            config = json.load(f)

    window = MainWindow(parent_conn, config)
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(image_data))

    window.setWindowIcon(pixmap)
    window.setWindowTitle("Barcode Scanner Display")

    window.show()
    sys.exit(app.exec())
    logging.info("Terminating process for scanner...")
    p.terminate()
    p.join()
