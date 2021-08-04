#!/usr/bin/env python3
from reader.readers import tokenize_pdf_statement
from ofx.domain import OfxBuilder
import sys
import os
import ntpath

"""
Creates OFX files from TD Bank checking account Statements as PDF. TD Bank only provides 90 days of online transactions 
which can be automatically downloaded to Quickbooks online. This program converts the PDF to OFX (as .qbo) for older 
transactions.

This is a quick and dirty hack since the statements for different accounts have different headers and order, 
but a lot quicker, easier, and less error prone than manually copying offline transactions from the PDF. 
"""


def usage():
    print("Usage: " + sys.argv[0] + " <import_file> <output_directory>")
    sys.exit(1)


if len(sys.argv) < 3:
    usage()

import_file_path = sys.argv[1]
import_file_name = ntpath.basename(import_file_path)
output_directory = sys.argv[2]

if not os.path.exists(output_directory):
    os.makedirs(output_directory)

lines = tokenize_pdf_statement(import_file_path)
ofx = OfxBuilder()
ofx.parse(lines)
output_file_path = os.path.join(output_directory, import_file_name.replace('.pdf', '.qbo'))
print("Writing OFX file " + output_file_path)
ofx_file = open(output_file_path, 'w')
ofx_file.write(ofx.pretty_print())
ofx_file.close()
