import os
import re
from datetime import datetime as dt
from tabulate import tabulate
import pandas as pd
import json
import socket
from queue import Queue

import serial
import time
from threading import Thread
import logging


def show_only_info(record):
    return record.levelname == "INFO"


# create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)


file_handler = logging.FileHandler("app.log", mode="a", encoding="utf-8")

formatter = logging.Formatter(
    "{asctime} - {levelname} - {message}",
    style="{",
    datefmt="%Y-%m-%d %H:%M",
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

console_handler.addFilter(show_only_info)

logger.addHandler(console_handler)
logger.addHandler(file_handler)


class ScanReaderThread(Thread):

    def __init__(self, config : json, queue):
        Thread.__init__(self)
        logger.debug('Starting thread ok')
        self.config = config
        logging.info('Listening at ' + self.config.get('COM'))
        self.ser = serial.Serial(self.config.get('COM'), self.config.get('Baud'), timeout=self.config.get('timeout'))
        self.queue = queue

    def run(self):
        while True:
            if self.ser.in_waiting > 0:
                data = self.ser.readline().decode('utf-8').rstrip()  # barcode
                process_data(data, self.queue)


class PLCSenderThread(Thread):

    def __init__(self, queue, tcp):
        Thread.__init__(self)
        self.queue = queue
        self.tcp = tcp
    
    def run(self):
        while True:
            data = self.queue.get()
            self.tcp.send(data)
            self.queue.task_done()


class TCPClient:
    def __init__(self, host, port, recv=4096):
        self.host = host
        self.port = port
        self.recv_bytes = recv
    
    def send(self, data : int):
        logger.info(f'Sending to PLC --- {dt.now()}')
        retry  = 3
        while retry > 0:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((self.host, self.port))
                    logger.info(f'Sending  {data} to plc')
                    s.sendall(data.to_bytes(2, 'big'))
                    resp = s.recv(self.recv_bytes)
                    logger.info(f'Reply from TCP server: {resp}')
                    retry=0
            except ConnectionRefusedError:
                logger.error("TCP connection refused",exc_info=True)
                time.sleep(5)
                retry -= 1
            except AttributeError:
                logger.error(f'Data is not int : {data}', exc_info=True)
                time.sleep(5)
                retry = -1

def create_dir(dest_folders):
    
    try:
        os.makedirs(dest_folders, exist_ok=True)
    except Exception as e:
        logging.error("Error while creating directory", exc_info=True)


def create_excel(data, data_header, dest_folders, filename):
    target_file = os.path.join(dest_folders, filename)
    exists = True  # does a file on same day exist to use
    try:
        df = pd.read_excel(target_file, index_col=False)
    except:
        exists = False

    if not exists:
        df = pd.DataFrame(data, columns=data_header)
    else:
        logger.info('adding row')
        logger.info(data)
        df.loc[len(df)] = data[0]

    df.to_excel(target_file, index=False)


def save_to_file(prefix, input_val, queue):

    scan = re.findall(r"MA.*", input_val)[0]
    data_header = ['Model', 'Packing code', 'Quantity']
    data = []
    data_row = []
    year = dt.today().strftime('%Y')
    ref_no_re = re.findall(r"\d{7}" + year, scan)[0]
    ref_no =  re.match(r"^\d{7}", ref_no_re).group()
    # data_row.append(ref_no)
    logger.info(f'Ref no.: {ref_no}')

    model_and_pack_code_re = re.findall(r"-\d{4}\d[A-Z]", scan)
    model_and_pack_code = model_and_pack_code_re[0]
    model_pack_groups = re.search(r"(\d{4})(\d[A-Za-z])", model_and_pack_code)

    # model no.
    model_no = model_pack_groups.groups()[0]
    data_row.append(model_no)

    # Packaging no.
    pack_code = model_pack_groups.groups()[1]
    data_row.append(pack_code)

    # order no.
    order_no = re.search(r"\d{9}$", scan).group()
    #data_row.append(order_no)
    logger.info(f'Order no.: {order_no}')

    # quantity
    qty = re.search(r"(?<=0000)\d{3}[A-Z]", scan).group()
    data_row.append(qty[:-1])

    # send this info to PLC
    queue.put(int(qty[:-1]))
    logger.info("Waiting for PLC transmission...")
    queue.join()

    data.append(data_row)
    print(tabulate(data, headers=data_header, tablefmt="grid", showindex="always"))

    _date = dt.today().strftime('%Y_%m_%d')
    dest_folders = os.path.join(os.getcwd(), _date)
    create_dir(dest_folders)
    create_excel(data, data_header, dest_folders, 'MRE_QR_kanban_info.xlsx')
    

def save_to_disk(prefix, lot_number):
    data = []
    data_header = ['Lot no.']
    data.append(lot_number)
    _date = dt.today().strftime('%Y_%m_%d')
    dest_folders = os.path.join(os.getcwd(), _date)
    create_dir(dest_folders)
    create_excel(data, data_header, dest_folders, 'lot_numbers.xlsx')


def process_data(data : str, queue):
    if data.startswith('DISC'):
        save_to_file('DISC', data, queue)
    elif data.startswith('MA'):
        save_to_disk('MA', data)


def process_with_threads(conf : json):
    com_info = conf.get('settings')
    
    queue = Queue()
    try:
        for i in range(len(com_info)):
            logger.info(com_info[i])
            t = ScanReaderThread(com_info[i], queue)
            t.daemon = True
            t.start()
    except Exception as e:
        logger.error("Scanner thread creation failed", exc_info=True)
    
    tcp = TCPClient(conf.get('PLC_TCP_IP'), conf.get('PLC_TCP_PORT'))
    try:
        t = PLCSenderThread(queue, tcp)
        t.daemon = True
        t.start()
    except Exception as e:
        logger.error("PLC sender thread creation failed", exc_info=True)

    while True:
        try:
            logger.debug("Health check OK")
            time.sleep(60)
        except KeyboardInterrupt as e:
            print("shutting down ...")
            break


if __name__=='__main__':
    with open('config.json', 'r') as f:
        config = json.load(f)

    process_with_threads(config)
