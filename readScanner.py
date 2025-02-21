import os
import re
from datetime import datetime as dt
from tabulate import tabulate
import pandas as pd
import json

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

    def __init__(self, config : json):
        Thread.__init__(self)
        logger.debug('Starting thread ok')
        self.config = config
        logging.info('Listening at ' + self.config.get('COM'))
        self.ser = serial.Serial(self.config.get('COM'), self.config.get('Baud'), timeout=self.config.get('timeout'))
        
    def run(self):
        while True:
            if self.ser.in_waiting > 0:
                data = self.ser.readline().decode('utf-8').rstrip()
                process_data(data)


def save_to_file(prefix, input_val):
    scan = re.findall(r"MA.*", input_val)[0]
    data_header = ['Ref No.', 'Model', 'Packing code', 'Order no.', 'Qty']
    data = []
    data_row = []
    year = dt.today().strftime('%Y')
    ref_no_re = re.findall(r"\d{7}" + year, scan)[0]
    ref_no =  re.match(r"^\d{7}", ref_no_re).group()
    data_row.append(ref_no)

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
    data_row.append(order_no)

    # quantity
    qty = re.search(r"(?<=0000)\d{3}[A-Z]", scan).group()
    data_row.append(qty)

    data.append(data_row)

    print(tabulate(data, headers=data_header, tablefmt="grid", showindex="always"))
 
    exists = True  # does a file on same day exist to use

    _date = dt.today().strftime('%Y_%m_%d')
    dest_folders = os.path.join(os.getcwd(), prefix, _date, model_no)

    try:
        os.makedirs(dest_folders, exist_ok=True)
    except Exception as e:
        logging.error("Error while creating directory", exc_info=True)

    target_file = os.path.join(dest_folders, 'MRE_QR_kanban_info.csv') 
    try:
        df = pd.read_csv(target_file, index_col=False)
    except:
        exists = False

    if not exists:
        df = pd.DataFrame(data, columns=data_header)
    else:
        print('adding row')
        print(data)
        df.loc[len(df)] = data[0]

    df.to_csv(target_file, index=False)


def save_to_disk(prefix, data):

    _date = dt.today().strftime('%Y_%m_%d')
    dest_folders = os.path.join(os.getcwd(), prefix, _date)
    try:
        os.makedirs(dest_folders, exist_ok=True)
    except Exception as e:
        logging.error("Error while creating directory", exc_info=True)
    
    filename = os.path.join(dest_folders, 'lot_numbers.txt')

    with open(f'{filename}', 'a+') as f:
        f.write(f'{data}\n' )

def serial_input(ser):
    
    if ser.in_waiting > 0:
        data = ser.readline().decode('utf-8').rstrip()
        process_data(data)


def use_input():
    data = input("Ready for barcode scanner... ")
    process_data(data)


def process_data(data):
    if data.startswith('DISC'):
        save_to_file('DISC', data)
    elif data.startswith('MA'):
        save_to_disk('MA', data)
    

def process_with_threads(conf):
    com_info = conf.get('settings')
    
    try:
        for i in range(len(com_info)):
            
            print(com_info[i])
            t = ScanReaderThread(com_info[i])
            
            t.daemon = True

            t.start()

    except Exception as e:
        logger.error("Thread creation failed", exc_info=True)

    while True:
        try:
            logger.info("Waiting for input...")
            time.sleep(20)
        except KeyboardInterrupt as e:
            print("shutting down ...")
            break


# test
def process_scanned_data(config):
    print('starting barcode scanner reader...')
    is_serial = config.get('use_serial')
    if is_serial:
        ser = serial.Serial(config.get('COM'), config.get('Baud'), timeout=config.get('timeout'))
    while True:
        try:
            if is_serial:
                serial_input(ser)
            else:
                use_input()
        except KeyboardInterrupt:
            print("shutting down...")
            if ser.is_open:
                ser.close()
            break


if __name__=='__main__':
    with open('config.json', 'r') as f:
        config = json.load(f)

    process_with_threads(config)
