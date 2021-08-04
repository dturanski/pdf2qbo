from ofxtools.models import *
from ofxtools.utils import UTC
from decimal import Decimal
from datetime import datetime
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
import pytz
from ofxtools.header import make_header


def pop(lines):
    """
    Pop from the top of list, this has the (desired) side-effect of removing the first line from the list.
    :param lines: the list of extracted text fields, one per line
    :return: the next line
    """
    return lines.pop(0)


def dump_lines(lines):
    """
    Dump the contents. Useful for debugging.
    :param lines: the list of extracted text fields, one per line
    :return: None
    """
    for line in lines:
        print(line)


class OfxBuilder:
    """
    Build the OFX object. Specific logic for TD Bank.
    see https://github.com/csingley/ofxtools.
    """

    # These values are specific to my bank.
    fi_org = 'CommerceBank'
    fid = '1002'
    bankid = '0111030'

    def __init__(self):
        self.statement_start_date = None
        self.statement_end_date = None
        self.account_number = None
        self.year = None
        self.starting_statement_balance = None
        self.ending_statement_balance = None

    def parse(self, lines):
        """
        Each transaction, is contained in multiple lines, starting with the MM/dd date. This keeps track of state by
        matching specific headers.
        :param lines: the list of extracted text fields, one per line
        :return: an instance of ofxtools.models.OFX, a document structure conforming to the OFX spec
        """
        dump_lines(lines)
        statement_transactions = []
        rollover_year = True
        done = False
        processing_checks = False  # Manually written checks are handled differently

        while len(lines) and not done:
            line = pop(lines)
            if line.startswith("Checks Paid"):
                # We hit the 'Checks Paid' section, will parse check transactions from there.
                processing_checks = True
                print("\n*** Processing Checks Paid")
            elif line.startswith('Electronic Payments'):
                # This may come after 'Checks Paid'
                processing_checks = False
            if line.startswith('Statement Period:'):
                # capture the statement start and end dates, and year which must be provided for the transaction dates
                self.statement_start_date, self.statement_end_date = StatementPeriodBuilder.parse(lines)
                self.year = self.statement_start_date.year
            elif line.startswith('Primary Account #:'):
                # capture the account number
                line = pop(lines)
                self.account_number = line
            elif line.startswith('Statement Balance as of'):
                # capture the starting and ending balance, the first one of these is the starting, second ending
                line = pop(lines)
                if self.starting_statement_balance:
                    self.ending_statement_balance = line.replace(',', '')
                else:
                    self.starting_statement_balance = line.replace(',', '')
            elif line.startswith('Beginning Balance'):
                line = pop(lines)
                self.starting_statement_balance = line.replace(',', '')
            elif line.startswith('Ending Balance'):
                line = pop(lines)
                self.ending_statement_balance = line.replace(',', '')
            elif line.startswith('DAILY BALANCE SUMMARY') or line.startswith('INTEREST SUMMARY'):
                # Signals end of processing, could be either header
                done = True
            elif not done:
                # if the line starts with a date, than this is the first line of a transaction.
                # capture the day and month. Assumes the transactions are in chronological order.
                search = re.search("^(\d{2})/(\d{2})", line)
                if search:
                    month = int(search.group(1))
                    day = int(search.group(2))
                    # Rollover year if December/January statement
                    if self.statement_start_date.month == 12 and month == 1 and rollover_year:
                        self.year += 1
                        rollover_year = False
                    txn_date = datetime(month=month, day=day, year=self.year, tzinfo=UTC)
                    print("\ntransaction on " + line)
                    # Create an OFX STMTTRN object, skip check entries unless we are in the `Checks Paid` section
                    statement_transaction = StatementTransactionBuilder().parse(lines, txn_date, processing_checks)

                    # For some reason, we need to explicitly check for None, standard Python truth doesn't work here.
                    if not statement_transaction is None:
                        print("adding transaction")
                        statement_transactions.append(statement_transaction)
                    else:
                        print("***NOTE***: deferred paper check transaction until 'Checks Paid' section")

        print("Beginning Balance-----------> " + self.starting_statement_balance)
        print("Ending Balance-----------> " + self.ending_statement_balance)

        # We're done processing the PDF data. Create the OFX document.
        status = STATUS(code=0, severity='INFO')
        ledgerbal = LEDGERBAL(balamt=Decimal(self.ending_statement_balance), dtasof=self.statement_end_date)
        bank_account_from = BANKACCTFROM(bankid=OfxBuilder.bankid, acctid=self.account_number, accttype='CHECKING')

        # This contains the statement_transactions list from above.
        bank_tran_list = BANKTRANLIST(*statement_transactions,
                                      dtstart=self.statement_start_date,
                                      dtend=self.statement_end_date)

        stmtrs = STMTRS(curdef='USD', bankacctfrom=bank_account_from, ledgerbal=ledgerbal, banktranlist=bank_tran_list)
        stmttrnrs = STMTTRNRS(trnuid='0', status=status, stmtrs=stmtrs)
        bankmsgsrs = BANKMSGSRSV1(stmttrnrs)
        fi = FI(org=self.fi_org, fid=self.fid)  # Required for Quicken compatibility
        sonrs = SONRS(status=status, dtserver=datetime.now(UTC), language='ENG', fi=fi)
        signonmsgs = SIGNONMSGSRSV1(sonrs=sonrs)
        self.ofx = OFX(signonmsgsrsv1=signonmsgs, bankmsgsrsv1=bankmsgsrs)

    def pretty_print(self):
        """
        Use this to render the OFX as a formatted XML str
        :return: the XML str
        """
        root = self.ofx.to_etree()
        message = ET.tostring(root).decode()
        header = str(make_header(version=220))
        return minidom.parseString(header + message).toprettyxml(indent="   ")


class StatementPeriodBuilder:
    @classmethod
    def parse(cls, lines):
        """
        Dates formatted for OFX spec. The time zone is hard coded, and incorrect, but it doesn't seem to matter
        :param lines:
        :return: the start_time and end_time for the statement
        """
        line = pop(lines)
        start, end = line.split("-")
        timezone = pytz.timezone("GMT")
        start_time = datetime.strptime(start, '%b %d %Y')
        start_time = timezone.localize(start_time)
        end_time = datetime.strptime(end, '%b %d %Y')
        end_time = timezone.localize(end_time)

        return [start_time, end_time]


class StatementTransactionBuilder:
    def __init__(self):
        self.__date = None
        self.__description = None
        self.__trntype = None
        self.__year = None
        self.__amount = 0.0

    def fitid(self, txn_date, amount):
        """
        Build a FITID from the date and amount. The type is made up. Not sure what the convention is or what happens
        if you have duplicate FITID.
        <TRNAMT>-3563.44
        <FITID>20210719000003563441
        """
        txn_type = 1
        if amount > 0.00:
            txn_type = 2

        return "%d%02d%02d%05d%d%d" % (txn_date.year, txn_date.month, txn_date.day, 0, abs(int(amount * 100)), txn_type)

    def parse(self, lines, txn_date, processing_checks):
        """
        Parse transaction lines.
        :param lines: the remaining, unconsumed text fields
        :param txn_date: the complete date built from the given MM/dd and the calculated year.
        :param processing_checks: True if we're handling 'Checks Paid'.
        :return: an instance of STMTTRN or None, if it's a check entry that we will handle later.
        """
        trntype_hint = pop(lines)  # this line normally contains a keyword used to determine credit or debit.
        trntype = None
        for credit_type in ['DEPOSIT', 'CREDIT', 'REFUND']:  # Credit keywords
            if credit_type in trntype_hint.upper():
                trntype = 'CREDIT'
        if processing_checks:
            # for checks, this is only the check number, so just set the type for now.
            print("*********** CHECK **********")
            trntype = 'DEBIT'
        if not trntype:
            # Debit keywords
            for debit_type in ['ELECTRONIC PMT', 'PAY', 'WITHDRAW', 'DEBIT', 'FEE', 'CHARGE', 'PMT', 'OVERDRAFT PD']:
                if debit_type in trntype_hint.upper():
                    trntype = 'DEBIT'
        if not trntype:

            if not trntype_hint.startswith('Check #'):  # skip CHECK # entries, will handle them up later
                # Uh oh we hit something we don't recognize, better stop.
                raise ValueError("Unable to determine transaction type for " + trntype_hint)
            else:
                # Eat the next 2 lines for the skipped check
                print(pop(lines))
                print(pop(lines))
                return None

        # variable extra description lines possible, 0 or more, before we get the amount.
        description = ""
        if processing_checks:
            # the hint should contain the check number
            description = "Check # " + trntype_hint
        line = pop(lines)
        # keep appending to the description until we get to the line containing the amount, a properly formatted number,
        # with 2 decimal places, possibly containing a comma.
        # todo: This will break for transactions ge. 1,000,000.00
        while not re.match("^\d+,?\d+\.\d{2}$", line):
            description += " " + line
            line = pop(lines)
        if not description:
            # No extra description lines.
            description = trntype_hint

        amount = float(line.replace(',', ''))

        if trntype == 'DEBIT':
            # Debit is always negative, Credit positive for OFX.
            amount = -amount

        print("{%s %s %f %s %s}" % (trntype, txn_date, amount, description, self.fitid(txn_date, amount)))

        # Create the STMTTRN, the description max is 32 characters. Use the standard date format.
        return STMTTRN(trntype=trntype, dtposted=txn_date.strftime("%Y%m%d%H%M%S.%f")[:-3], trnamt=str(amount),
                       fitid=self.fitid(txn_date, amount),
                       name=description[:32], memo="")
