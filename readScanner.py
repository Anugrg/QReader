import re
from datetime import datetime as dt
from tabulate import tabulate
import pandas as pd
import json

import serial


def save_to_file(name, input_val):
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
    exists = True
    try:
        df = pd.read_csv('disc.csv', index_col=False)
    except:
        exists = False
    if not exists:
        df = pd.DataFrame(data, columns=data_header)
        
    else:
        print('adding row')
        print(data)
        df.loc[len(df)] = data[0]

    df.to_csv('disc.csv', index=False)


def save_to_disk(prefix, data):
    print(data)
    with open(f'{prefix}', 'a+') as f:
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
            if ser.is_open:
                ser.close()
            break


if __name__=='__main__':
    with open('config.json', 'r') as f:
        config = json.load(f)

    process_scanned_data(config)
