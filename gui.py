import sys
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
import pandas as pd
import os
from pathlib import Path


class TableModel(QtCore.QAbstractTableModel):

    def __init__(self, data):
        super().__init__()
        self._data = data

    def data(self, index, role):
        if role == Qt.DisplayRole:
            value = self._data.iloc[index.row(), index.column()]
            return str(value)

    def rowCount(self, index):
        return self._data.shape[0]

    def columnCount(self, index):
        return self._data.shape[1]

    def headerData(self, section, orientation, role):
        # section is the index of the column/row.
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return str(self._data.columns[section])

            if orientation == Qt.Vertical:
                return str(self._data.index[section])


class MainWindow(QtWidgets.QMainWindow):

    def __init__(self, data):
        super().__init__()
        self.setWindowTitle("Barcode Reader Display")
        self.table = QtWidgets.QTableView()

        self.model = TableModel(data)
        self.table.setModel(self.model)

        self.setCentralWidget(self.table)


app=QtWidgets.QApplication(sys.argv)


file_path = Path(os.getcwd(), '2025_02_25', 'MRE_QR_kanban_info.xlsx' )
xls = pd.read_excel(file_path, index_col=False)
window=MainWindow(xls)
window.show()
app.exec()