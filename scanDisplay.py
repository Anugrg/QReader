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
from queue import Queue
from queue import Queue


from PySide6.QtWidgets import (QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QDateEdit, QSpinBox)
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


class CustomLineEdit(QLineEdit):
    text_set = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setText(self, text):
        super().setText(text)
        self.text_set.emit(text)


class TcpSignals(QObject):
    result = Signal(tuple)
    fail = Signal(tuple)
    conn = Signal(int)


class TCPServerSignals(QObject):
    data = Signal(tuple)
    conn = Signal(int)
    report = Signal(str)
    alive = Signal(int)

class Communicator(QObject):
    data_received = Signal(list)


class TCPServerWorker(QRunnable):
    
    def __init__(self, ip, port, table, row, col, outfeed_data=[]):
        super().__init__()
        self.host = ip
        self.port = port
        self.signal = TCPServerSignals()
        self.running = True
        self.close_conn = False
        self.plc_ready = False
        self.table = table
        self.row = row
        self.col = col
        self.outfeed = False
        self.outfeed_data = outfeed_data

    def stop(self):
        self.running = False
        self.close_conn = True

    @Slot()
    def run(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.host, self.port))
        server.listen()

        logging.info(f"[*] Listening on {self.host}:{self.port}")
        try:
            while self.running:
                self.signal.alive.emit(1)
                if self.close_conn == True:
                    break
                client_socket, addr = server.accept()
                print(f"[*] Accepted connection from {addr[0]}:{addr[1]} {self.running}")
                self.signal.conn.emit(1)
                data = client_socket.recv(4096)
                ret = self.process_msg(data)
                if ret:
                    print(ret)
                    client_socket.sendall(ret)
                client_socket.close()

        except KeyboardInterrupt:
            sys.exit()
        except ValueError:
            self.signal.conn.emit(0)
            logger.error("Value Error", exc_info=True)
        except Exception as e:
            self.signal.conn.emit(0)
            self.signal.alive.emit(0)
            logger.error("Socket failure", exc_info=True)

    def process_msg(self, data):
        msg = data.decode('ASCII')
        resp = ''
        cmd_id = msg.split('|')[0]
        num_rows = self.table.rowCount()
        if num_rows > 0:
            if cmd_id == 'M100':
                if msg.split('|')[1] == '200':
                    self.signal.report.emit('PLC is ready to send')
                    self.plc_ready = True
                else:
                    self.signal.report.emit('PLC is not ready')
                    
            if cmd_id == 'M104' and self.plc_ready:
                # outfeed check
                if self.outfeed and len(self.outfeed_data) > 0:
                    print(self.outfeed_data)
                    model, order, qty = self.outfeed_data
                    ret_msg = '|'.join(['R104', model, qty ])
                    self.signal.data.emit((msg, self.row))
                    return ret_msg.encode('ASCII')
                else:
                    self.outfeed = True
                    self.signal.report.emit('OUTFEED')
            elif cmd_id == 'M106':
                self.signal.data.emit((msg, self.row))
            elif self.col < 7 and self.row < num_rows and self.plc_ready:
                model = self.table.item(self.row, 1).text()
                req_qty = self.table.item(self.row, self.col).text()
                status = self.table.item(self.row, 7).text()  # status column helps keep track
                if status != 'COMPLETED':
                    if cmd_id == 'M100' and status == "NEXT":
                        # send qty and model to PLC
                        self.signal.data.emit((msg, self.row))
                        return self.create_req_qty_msg(model, req_qty)                    
                    else:
                        self.signal.data.emit((msg, self.row))

    def create_req_qty_msg(self, model : str, req_qty : str):
        data = '|'.join(['R100', model, req_qty])
        return data.encode('ASCII')


    def reassign(self, row, col):
        self.row = row
        self.col = col


class TCPWorker(QRunnable):
    '''
    Worker thread
    '''

    def __init__(self, table, ip, port, row, col):
        super().__init__()
        self.table = table
        self.host = ip
        self.port = port
        self.signal = TcpSignals()
        self.active = False
        self.row = row
        self.col = col
        self.running = True
        self.plc_ready = False
        self.plc_reply = ''

    """def __init__(self, qty : int, host, port, row):
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
                self.signal.fail.emit((result, self.row))"""

    @Slot()
    def run(self):
        self.active = True
        while self.running:
            self.start_plc_comm()
            time.sleep(3)

    def start_plc_comm(self):

        if self.plc_ready:
            print('PLC Ready')
            logging.info('PLC Ready')
            num_rows = self.table.rowCount()

            if self.col < 7 and self.row < num_rows:
                logging.info('Working to send')
                model = self.table.item(self.row, 1).text()
                req_qty = self.table.item(self.row, self.col).text()
                status = self.table.item(self.row, 7).text()  # status column helps keep track
                if status != "COMPLETED":
                    if self.col == 3:
                        self.create_req_qty_msg(model, req_qty)
                    elif self.col == 4:
                        self.create_req_good_msg(model)
                    elif self.col == 5:
                        self.create_req_defect_msg(model)
                    elif self.col == 6:
                        self.create_req_completed_msg(model)

    @Slot(str)
    def handle_plc_msg(self, msg):
        self.signal.conn.emit(1)
        self.plc_reply = msg.split('|')
        print(self.plc_reply)
        cmd_id = self.plc_reply[0]
        print('Rec from server thread')
        if cmd_id == 'M100':  # PLC ready msg
            if not self.plc_ready:
                self.plc_ready = True
        else:
            # result = int.from_bytes(resp, 'big')
            resp = self.plc_reply
            self.plc_ready = True
            print(self.plc_ready, self.col)
            if resp:
                self.signal.result.emit((resp, self.row, self.col))
            else:
                self.signal.fail.emit((resp, self.row))


    def create_req_qty_msg(self, order_no : str, req_qty : str):
        data = '|'.join(['R101', order_no, req_qty])
        # self.send_tcp(data)

    def create_req_good_msg(self, order_no : str):
        data = '|'.join(['R102', order_no])
        # self.send_tcp(data)

    def create_req_defect_msg(self, order_no : str):
        data = '|'.join(['R103', order_no])
        # self.send_tcp(data)
    
    def create_req_completed_msg(self, order_no : str):
        data = '|'.join(['R104', order_no])
        # self.send_tcp(data)

    def send_tcp(self, payload : str):
        logger.info(f'Sending to PLC --- {dt.now()}')
        data = payload.encode('ASCII')
        # success = True
        retry  = 2
        while retry > 0:
            try:
                logging.info('Starting client in tcp client thread')
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((self.host, self.port))
                    logger.info(f'Sending {data} to plc')
                    # s.sendall(self.data.to_bytes(2, 'big'))

                    s.sendall(data)
                    
                    self.plc_ready = False
                    resp = s.recv(4096)
                    retry = 0
                    # if resp:
                    #     logger.info(f'Reply from TCP server: {resp}')
                    #     success = True
                    #     retry = 0
                    # else:
                    #     logger.info(f'No response from plc')

            except ConnectionRefusedError:
                logger.error("TCP connection refused", exc_info=True)
                self.signal.conn.emit(0)
                time.sleep(1)
                success = False
                retry -= 1
            except AttributeError:
                logger.error(f'Data is not int : {data}', exc_info=True)
                time.sleep(1)
                retry = -1
                success = False
            except socket.timeout:
                logger.error("Timeout", exc_info=True)
                time.sleep(2)
    

    def reassign(self, row, col):
        self.col = col
        self.row = row

    def is_active(self):
        return self.active

    def stop(self):
        self.running = False


class TableApp(QWidget):

    def __init__(self, pipe, config):
        super().__init__()
        logger.info("Table rendered...")
        logger.info(pipe)
        self.pipe = pipe
        self.infeed = False
        self.outfeed = False
        self.plc_row = 0  # tracks which row to send to PLC

        self.tcp_ip = config.get('PLC_TCP_IP')
        self.tcp_port = config.get('PLC_TCP_PORT')
        self.server_ip = config.get('TCP_SERVER')
        self.server_port = config.get('TCP_SERVER_PORT')
        self.scanner_infeed = config.get('INFEED')
        self.scanner_outfeed = config.get('OUTFEED')
        self.travel_sheet = ''
        self.next = 0  # track which row in process

        self.initUI()
        logger.info("Setting up Signal...")
        # thread to fetch data from pipe
        self.communicator = Communicator()
        self.communicator.data_received.connect(self.add_row)
        self.t = Thread(target=self.read_from_pipe)
        self.t.daemon = True
        self.t.start()
        self.queue = Queue()
        self.threadpool = QThreadPool()
        self.server = TCPServerWorker(self.server_ip, self.server_port, self.table, 0, 3)
        # self.worker = TCPWorker(self.table, self.tcp_ip, self.tcp_port, 0, 3)
        # self.server.signal.data.connect(self.worker.handle_plc_msg)
        self.server.signal.conn.connect(self.check_tcp_status)
        self.server.signal.data.connect(self.get_plc_status)
        self.server.signal.report.connect(self.report_plc_state)
        self.server.signal.alive.connect(self.check_pulse)
        self.threadpool.start(self.server)


    def closeEvent(self, event):
        self.server.stop()
        # self.worker.stop()
        self.threadpool.waitForDone()
        super().closeEvent(event)


    def initUI(self):
        self.setWindowTitle('Barcode Scanner Reader Display')
        self.setGeometry(100, 100, 5000, 800)

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

        self.plc_state_label = QLabel("PLC State")
        self.plc_state_text = QLineEdit()
        self.plc_state_text.setReadOnly(True)

        self.row_label = QLabel("Active Row")

        self.row_text = QLineEdit()
        self.row_text.setReadOnly(True)

        self.tcp_label = QLabel("TCP Status")
        self.tcp_text = QLineEdit()
        self.tcp_text.setReadOnly(True)

        # self.chk_conn_button = QPushButton('Check', self)
        # self.chk_conn_button.clicked.connect(self.check_tcp_status)

        plc_layout.addWidget(self.date_label)
        plc_layout.addWidget(self.date_field)

        plc_layout.addWidget(self.plc_tcp_status)
        plc_layout.addWidget(self.plc_tcp_status_text)

        plc_layout.addWidget(self.plc_state_label)
        plc_layout.addWidget(self.plc_state_text)

        plc_layout.addWidget(self.row_label)
        plc_layout.addWidget(self.row_text)

        plc_layout.addWidget(self.tcp_label)
        plc_layout.addWidget(self.tcp_text)

        # plc_layout.addWidget(self.chk_conn_button)
        
        plc_layout.setSpacing(5)
        plc_layout.setAlignment(self.plc_tcp_status_text, Qt.AlignLeft)
        plc_layout.addStretch()

        # Input layout
        input_layout = QHBoxLayout()

        self.name_field = CustomLineEdit(self)
        self.name_field.setPlaceholderText('Lot no.')
        self.name_field.setMinimumWidth(350)
        self.name_field.text_set.connect(self.process_lot_num)

        self.label = QLabel("Lot no.")

        input_layout.addWidget(self.label)
        input_layout.addWidget(self.name_field)

        # self.infeed_button = QPushButton('Send to PLC', self)
        # self.infeed_button.clicked.connect(self.send_to_plc)
        # input_layout.addWidget(self.infeed_button)

        self.success_color = QColor(200, 255, 200)
        self.fail_color = QColor(255, 200, 200)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(['Order', 'Model', 'Packing Code', 'Quantity Required','Good Quantity', 'Defective Quantity', 'Completed', 'Status'])
        self.table.itemChanged.connect(self.calculate_quantities)
        self.table.model().rowsInserted.connect(self.calculate_quantities)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        # Clear button
        self.clear_button = QPushButton('Clear', self)
        self.clear_button.clicked.connect(self.clear_table)

        self.reset_button = QPushButton('Reset all status', self)
        self.reset_button.clicked.connect(self.reset_status)

        self.reset_one_button = QPushButton('Reset one status', self)
        self.reset_one_button.clicked.connect(self.reset_status_one)

        # self.save_table_btn = QPushButton('Save', self)
        # self.save_table_btn.clicked.connect(self.save_table)

        self.good_label = QLabel("Good Qty")
        self.good_field = QLineEdit()
        self.good_field.setReadOnly(True)

        self.defect_label = QLabel("Defective Qty")
        self.defect_field = QLineEdit()
        self.defect_field.setReadOnly(True)

        self.completed_label = QLabel("Completed Qty")
        self.completed_field = QLineEdit()
        self.completed_field.setReadOnly(True)

        layout.addLayout(plc_layout)
        layout.addLayout(input_layout)
        layout.addWidget(self.table)

        self.reset_row_label = QLabel("Reset Row")
        self.spin_box = QSpinBox()
        self.spin_box.setRange(1, 100)

        foot_layout = QHBoxLayout()
        foot_layout.addWidget(self.good_label)
        foot_layout.addWidget(self.good_field)

        foot_layout.addWidget(self.defect_label)
        foot_layout.addWidget(self.defect_field)

        foot_layout.addWidget(self.completed_label)
        foot_layout.addWidget(self.completed_field)
        foot_layout.addWidget(self.reset_row_label)
        foot_layout.addWidget(self.spin_box)
        foot_layout.addWidget(self.reset_one_button)
        foot_layout.addWidget(self.reset_button)
        # foot_layout.addWidget(self.save_table_btn)
        foot_layout.addWidget(self.clear_button)

        layout.addLayout(foot_layout)
        self.setLayout(layout)

    def check_pulse(self, status):
        if status:
            self.tcp_text.setText('Alive')
            self.tcp_text.setStyleSheet("background-color: green;color:white")
        else:
            self.tcp_text.setText('Down')
            self.tcp_text.setStyleSheet("background-color: red;color:white")

    def report_plc_state(self, report):
        self.plc_state_text.setText(report)
        self.plc_state_text.setStyleSheet("background-color: green;color:white")

    def calculate_quantities(self):
        rows = self.table.rowCount()
        if rows > 0:
            good = 0
            defect = 0
            complete = 0

            for i in range(rows):
                if self.table.item(i, 4) and self.table.item(i, 4).text():
                    good += int(self.table.item(i, 4).text())
                if  self.table.item(i, 5) and self.table.item(i, 5).text():
                    defect += int(self.table.item(i, 5).text())
                if  self.table.item(i, 6) and self.table.item(i,6).text():
                    complete += int(self.table.item(i,6).text())

            self.good_field.setText(str(good))
            self.defect_field.setText(str(defect))
            self.completed_field.setText(str(complete))


    def process_lot_num(self):
        # Process travel sheet which triggers thread
        # to process kanbans from table
        travel_sheet_num = self.name_field.text()
        logger.info(travel_sheet_num.strip())
        if travel_sheet_num.strip() != "":
            logger.info(f"Rec: {travel_sheet_num}")
            if travel_sheet_num != self.travel_sheet:  # new travel sheet
                self.travel_sheet = travel_sheet_num  # update travel sheet number
                # if not self.worker.is_active():
                #     logger.info("Starting PLC thread...")
                #     # running for first time
                #     self.worker.signal.result.connect(self.get_plc_status)
                #     self.worker.signal.fail.connect(self.get_plc_status)
                #     self.worker.signal.conn.connect(self.toggle_tcp_conn)
                #     self.threadpool.start(self.worker)
                #     self.set_col_text(0, 7, 'RUNNING')
                #     self.color_row(0, QColor(235, 169, 158))
                # elif not self.worker.running:
                #     self.worker.running = True


    def reset_style(self, widget, text):
        widget.setText(text)
        widget.setStyleSheet("background-color: lightgrey;color:white")

    def check_tcp_status(self, status):
        if status:
            self.plc_tcp_status_text.setText('CONNECTED')
            self.plc_tcp_status_text.setStyleSheet("background-color: green;color:white")
        else:
            self.plc_tcp_status_text.setText('FAILED')
            self.plc_tcp_status_text.setStyleSheet("background-color: red;color:white")
        # try:
        #     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        #         s.connect((self.tcp_ip, self.tcp_port))
        #         logger.info(s.getpeername())
        #         self.plc_tcp_status_text.setText('CONNECTED')
        #         self.plc_tcp_status_text.setStyleSheet("background-color: green;color:white")

        # except ConnectionRefusedError:
        #     self.plc_tcp_status_text.setText('FAILED')
        #     self.plc_tcp_status_text.setStyleSheet("background-color: red;color:white")
        #     logger.error("TCP connection refused", exc_info=True)


    def toggle_tcp_conn(self, status):
        if status:
            self.plc_tcp_status_text.setText('CONNECTED')
        else:
            self.plc_tcp_status_text.setText('FAILED')


    def read_from_pipe(self):
        """
        Receive data from process running
        threads to get value from scanned QR
        """
        while True:
            if self.pipe.poll():
                data = self.pipe.recv()
                logger.info(data)
                self.communicator.data_received.emit(data)


    def send_to_plc(self):
        '''
        Send qty to PLC via TCP
        '''
        if not self.infeed:  # if outfeed is false it means
            for row in range(self.table.rowCount()):
                if self.table.item(row, 6).text()  == 'COMPLETED':
                    continue

                qty = self.table.item(row, 3).text()
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
            self.set_col_text(row, 6, 'RUNNING')
            self.color_row(row, QColor(	235, 169, 158))
        except:
            logging.error("Worker failed", exc_info=True)


    def set_col_text(self, row, col, text):
        '''
        Change text in col cell
        '''
        self.table.setItem(row, col, QTableWidgetItem(text))


    def get_plc_status(self, result):
        # Receives data TCPServer worker
        msg, row = result
        msg_list = msg.split('|')
        temp = row + 1
        self.row_text.setText(str(temp))

        if msg_list[0] == 'M100':
            if msg_list[1] == '200':
                logger.info(f"Reply from plc:{msg_list}")
                self.server.signal.report.emit('Reply to PLC with kanban data')
                self.set_col_text(row, 7, 'RUNNING')
                self.color_row(row, QColor(235, 169, 158))
                self.server.reassign(row, 4)
            else:
                self.server.signal.report.emit('PLC reply error')
                self.set_col_text(row, 7, 'Fail')

        elif msg_list[0] == 'M101':
            self.server.signal.report.emit('Received good qty')
            self.set_col_text(row, 4, msg_list[2])
            self.server.reassign(row, 5)
        elif msg_list[0] == 'M102':
            self.server.signal.report.emit('Received defective qty')
            self.set_col_text(row, 5, msg_list[2])
            self.server.reassign(row, 6)
        elif msg_list[0] == 'M103':
            self.server.signal.report.emit('Received completed qty')
            self.set_col_text(row, 6, msg_list[2])
        elif msg_list[0] == 'M104':
            self.server.signal.report.emit('PLC outfeed scan sent')
        elif msg_list[0] == 'M105':
            if msg_list[1] == '200':
                self.server.signal.report.emit('PLC kanban match success')
                self.set_col_text(row, 7, "COMPLETED")
                self.color_row(row, QColor(	144, 238, 144))
                self.write_to_file(row)
                self.server.plc_ready = False  # plc needs to send ready msg again
                self.server.outfeed = False
                self.server.outfeed_data = []  # reset outfeed kanban
                row += 1  # go to next row
                self.server.reassign(row, 3)  # change row and col for thread
            else:
                self.server.signal.report.emit('PLC kanban mismatch')
                self.set_col_text(row, 7, "FAILED")
                self.color_row(row, self.fail_color)


    def write_to_file(self, row):
        data_header = ['Lot Number', 'Model', 'Packaging code', 'Quantity']
        data = []
        data_row = []
        data_row.append(self.name_field.text())
        data_row.append(self.table.item(row, 1).text())
        data_row.append(self.table.item(row, 2).text())
        data_row.append(self.table.item(row, 3).text())
        data.append(data_row)
        print(data)
        _date = dt.today().strftime('%Y_%m_%d')
        dest_folders = os.path.join(os.getcwd(), _date)
        scanner.create_dir(dest_folders)
        scanner.create_excel(data, data_header, dest_folders, 'MRE_QR_kanban_info.xlsx')


    def get_row_by_column_value(self, column, model) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, column)
            if item and item.text() == model:
                return row, self.table.item(row, 2).text()


    def get_col_value(self, row, col):
        return self.table.item(row, col).text()


    def check_row_exists(self, column, order):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, column)
            if item and item.text() == order:
                return True

        return False


    def check_outfeed(self, data : list):
        '''
        After infeed, rows are set
        At outfeed, check if scanned QR matches
        by sending qty again to PLC
        '''
        try:
   
            print(f"Outfeed scan {data}")
            if self.server.outfeed:
                if len(self.server.outfeed_data) > 0:
                    self.server.outfeed_data = []

                self.server.outfeed_data.extend([data[0], data[2], data[3]])

        except TypeError as e:
            logging.ERROR("Row is not present")


    @Slot(list)
    def add_row(self, data : list):
        logger.info(f"Data received: {data}")

        if data and len(data) > 1: # checking length so that we can seperate travel and kanban
             # data = [model no, package code, order no, qty, COM ]
            model, packing_code, order, quantity, COM = data

            if COM==self.scanner_outfeed:
                self.check_outfeed(data)

            elif COM==self.scanner_infeed:
                exists = self.check_row_exists(0, order)
                if not exists:
                    row_position = self.table.rowCount()
                    self.table.insertRow(row_position)
                    self.table.setItem(row_position, 0, QTableWidgetItem(order))
                    self.table.setItem(row_position, 1, QTableWidgetItem(model))
                    self.table.setItem(row_position, 2, QTableWidgetItem(packing_code))
                    self.table.setItem(row_position, 3, QTableWidgetItem(quantity))  # req quantity
                    self.table.setItem(row_position, 4, QTableWidgetItem('0'))  # good
                    self.table.setItem(row_position, 5, QTableWidgetItem('0'))  # defect 
                    self.table.setItem(row_position, 6, QTableWidgetItem('0'))  # completed quantity
                    self.table.setItem(row_position, 7, QTableWidgetItem('NEXT'))  # status
                    self.color_row(row_position, QColor(255, 200, 100))

        else:
            self.name_field.clear()
            self.name_field.setText(data[0])


    def color_row(self, row_indx, qcolor):
        cols = self.table.columnCount()
        for col in range(cols):
            item = self.table.item(row_indx, col)
            item.setBackground(QBrush(qcolor))


    def save_table(self):
        _date = dt.today().strftime('%Y_%m_%d')
        dest_folders = os.path.join(os.getcwd(), _date)
        rows = self.table.rowCount()
        if rows > 0:
            data = []
            data_header = ['Model', 'Packing code', 'Quantity']
            for row in range(rows):
                data.append([self.table.item(row, 0).text(), self.table.item(row, 1).text(), self.table.item(row, 2).text()])

            scanner.create_dir(dest_folders)
            scanner.create_excel(data, data_header, dest_folders, 'MRE_QR_kanban_info.xlsx')

        if bool(self.name_field.text()):
            scanner.save_to_disk(self.name_field.text(), dest_folders)


    def clear_table(self):
        self.table.setRowCount(0)
        self.name_field.clear()
        self.good_field.clear()
        self.defect_field.clear()
        self.completed_field.clear()
        self.server.reassign(0, 3)
        self.row_text.clear()

    def reset_status(self):
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 7, QTableWidgetItem('NEXT'))
            self.color_row(row, QColor(255, 200, 100))

        self.server.reassign(0, 3)
    
    def reset_status_one(self):
        row = self.spin_box.value() - 1    
        if row < self.table.rowCount():  
            self.table.setItem(row, 7, QTableWidgetItem('NEXT'))
            self.color_row(row, QColor(255, 200, 100))
            self.server.reassign(row, 3)
            self.row_text.clear()

# Parent window
class MainWindow(QMainWindow):
    def __init__(self, pipe, config, p):
        super().__init__()
        logger.info("Main window created...")
        #self.setFixedHeight(650)
        self.process = p
        self.table = TableApp(pipe, config)
        self.setCentralWidget(self.table)
    

    def closeEvent(self, event):
        self.table.close()  # Ensure the child window is closed
        event.accept()
        super().closeEvent(event)  # Call the base class implementation


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

    window = MainWindow(parent_conn, config, p)
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(image_data))

    window.setWindowIcon(pixmap)
    window.setWindowTitle("Barcode Scanner Display")

    window.show()
    logging.info("Terminating process for scanner...")

    sys.exit(app.exec())
    p.terminate()
    p.join()

