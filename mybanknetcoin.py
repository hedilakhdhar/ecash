"""
BanknetCoin

Usage:
  banknetcoin.py serve
  banknetcoin.py ping
  banknetcoin.py tx <from> <to> <amount>
  banknetcoin.py balance <name>

Options:
  -h --help     Show this screen.
"""

import uuid
from copy import deepcopy
from ecdsa import SigningKey, SECP256k1
from utils import serialize, deserialize, prepare_simple_tx
from identities import user_public_key, user_private_key
from docopt import docopt

import socketserver, socket, sys

host = '0.0.0.0'
port = 10005

address = (host, port)



#2 modifier spend message de sorte à comprendre l'intention
# ie : tx_in.outpoint et tx_outs



def spend_message(tx, index):
    outpoint = tx.tx_ins[index].outpoint
    return serialize(outpoint) + serialize(tx.tx_outs)

class Tx:

    def __init__(self, id, tx_ins, tx_outs):
        self.id = id
        self.tx_ins = tx_ins
        self.tx_outs = tx_outs

    def sign_input(self, index, private_key):
        signature = private_key.sign(spend_message(self,index))
        self.tx_ins[index].signature = signature

    def verify_input(self, index, public_key):
        tx_in = self.tx_ins[index]
        message = spend_message(self, index)
        return public_key.verify(tx_in.signature, message)

class TxIn:

    def __init__(self, tx_id, index, signature=None):
        self.tx_id = tx_id
        self.index = index
        self.signature = signature

    # @property
    # def spend_message(self):
    #     # FIXME missing recipient public key
    #     return f"{self.tx_id}:{self.index}".encode()

    @property
    def outpoint(self):
        return (self.tx_id, self.index)

class TxOut:

    def __init__(self, tx_id, index, amount, public_key):
        self.tx_id = tx_id
        self.index = index
        self.amount = amount
        self.public_key = public_key

    @property
    def outpoint(self):
        return (self.tx_id, self.index)

class Bank:

    def __init__(self):
        # (tx_id, index) -> TxOut (public_key)
        # (tx_id, index) -> public_key (lock)
        self.utxo = {}

    def update_utxo(self, tx):
        for tx_out in tx.tx_outs:
            self.utxo[tx_out.outpoint] = tx_out
        for tx_in in tx.tx_ins:
            del self.utxo[tx_in.outpoint]

    def issue(self, amount, public_key):
        id_ = str(uuid.uuid4())
        tx_ins = []
        tx_outs = [TxOut(tx_id=id_, index=0, amount=amount, public_key=public_key)]
        tx = Tx(id=id_, tx_ins=tx_ins, tx_outs=tx_outs)

        self.update_utxo(tx)

        return tx

    def validate_tx(self, tx):
        # 3 corriger cette fonction
        # créer verify input methode de tx
        # similitaire à sign.input mais prend
        # input index et public_key comme inputs
        # astuce utiliser enumerate
        in_sum = 0
        out_sum = 0

        for index, tx_in in enumerate(tx.tx_ins):
            assert tx_in.outpoint in self.utxo

            tx_out = self.utxo[tx_in.outpoint]
            # Verify signature using public key of TxOut we're spending
            tx.verify_input(index, tx_out.public_key)

            # Sum up the total inputs
            amount = tx_out.amount
            in_sum += amount

        for tx_out in tx.tx_outs:
            out_sum += tx_out.amount

        assert in_sum == out_sum

    def handle_tx(self, tx):
        # Save to self.utxo if it's valid
        self.validate_tx(tx)
        self.update_utxo(tx)

    def fetch_utxo(self, public_key):
        return [utxo for utxo in self.utxo.values()
                if utxo.public_key.to_string() == public_key.to_string()]

    def fetch_balance(self, public_key):
        # Fetch utxo associated with this public key
        unspents = self.fetch_utxo(public_key)
        # Sum the amounts
        return sum([tx_out.amount for tx_out in unspents])

class myTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

class TCPHandler(socketserver.BaseRequestHandler):

    def respond(self, command, data):
        message = prepare_message(command, data)
        serialized_message = serialize(message)
        self.request.sendall(serialized_message)

    def handle(self):
        serialized_message = self.request.recv(5000).strip()
        message = deserialize(serialized_message)
        command = message['command']
        data = message['data']
        print(f'got a message : {message}')

        if command == 'ping':
            self.respond('pong', '')

        elif command == 'balance':
            # public_key = user_public_key(data)
            balance = bank.fetch_balance(data)
            self.respond('balance_response', balance)

        elif command == 'utxo':
            # public_key = user_public_key(data)
            utxo = bank.fetch_utxo(data)
            self.respond('utxo_response', utxo)

        elif command == 'tx':
            try:
                bank.handle_tx(data)
                self.respond('tx_response', 'accepted')
            except:
                self.respond('tx_response', 'rejected')


bank = Bank()

def prepare_message(command, data):
    return {
    'command' : command,
    'data' : data
    }

def serve():
    server = myTCPServer(address, TCPHandler)
    server.serve_forever()

def send_message(command, data):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(address)

    message = prepare_message(command, data)
    serialized_message = serialize(message)
    sock.sendall(serialized_message)

    message_data = sock.recv(5000)
    message = deserialize(message_data)

    print(f'received : {message}')
    return message

def prepare_simple_tx(utxos, sender_private_key, recipient_public_key, amount):
    sender_public_key = sender_private_key.get_verifying_key()

    # Construct tx.tx_outs
    tx_ins = []
    tx_in_sum = 0
    for tx_out in utxos:
        tx_ins.append(TxIn(tx_id=tx_out.tx_id, index=tx_out.index, signature=None))
        tx_in_sum += tx_out.amount
        if tx_in_sum > amount:
            break

    # Make sure sender can afford it
    assert tx_in_sum >= amount

    # Construct tx.tx_outs
    tx_id = uuid.uuid4()
    change = tx_in_sum - amount
    tx_outs = [
        TxOut(tx_id=tx_id, index=0, amount=amount, public_key=recipient_public_key),
        TxOut(tx_id=tx_id, index=1, amount=change, public_key=sender_public_key),
    ]

    # Construct tx and sign inputs
    tx = Tx(id=tx_id, tx_ins=tx_ins, tx_outs=tx_outs)
    for i in range(len(tx.tx_ins)):
        tx.sign_input(i, sender_private_key)

    return tx

def main(args):
    if args['serve']:
        alice_public_key = user_public_key("alice")
        bank.issue(1000, alice_public_key)
        serve()
    elif args['ping']:
        send_message('ping', '')
    elif args['balance']:
        name = args['<name>']
        public_key = user_public_key(name)
        send_message('balance', public_key)
    elif args['tx']:
        # banknetcoin.py tx <from> <to> <amount>
        # Fetch sender utxo
        sender_private_key = user_private_key(args['<from>'])
        sender_public_key = user_public_key(args['<from>'])
        recipient_public_key = user_public_key(args['<to>'])
        amount = int(args['<amount>'])

        utxo_data = send_message('utxo', sender_public_key)
        utxo = utxo_data['data']
        # Prepare transaction

        tx = prepare_simple_tx(utxo, sender_private_key, recipient_public_key, amount)

        # Send transaction to bank
        response = send_message('tx', tx)
        print(response)

    else:
        print('invalid command')


if __name__ == '__main__':
    main(docopt(__doc__))
