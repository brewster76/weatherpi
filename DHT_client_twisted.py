from twisted.internet import task
from twisted.internet.defer import Deferred
from twisted.internet.protocol import ClientFactory
from twisted.protocols.basic import LineReceiver

import json

import DHT_server


class EchoClient(LineReceiver):
    end = "Bye-bye!"

    def __init__(self):
        self.temperature = None
        self.humidity = None

    def connectionMade(self):
        self.sendLine("Send me data")

    def lineReceived(self, line):
        if "DHT22 server" == line:
            return

        print line

        (temp, humidity) = json.loads(line)

        print "received: %.1f C, %.1f humidity" % (temp, humidity)

        if line == self.end:
            self.transport.loseConnection()



class EchoClientFactory(ClientFactory):
    protocol = EchoClient

    def __init__(self):
        self.done = Deferred()


    def clientConnectionFailed(self, connector, reason):
        print('connection failed:', reason.getErrorMessage())
        self.done.errback(reason)


    def clientConnectionLost(self, connector, reason):
        print('connection lost:', reason.getErrorMessage())
        self.done.callback(None)



def main(reactor):
    factory = EchoClientFactory()
    reactor.connectTCP('localpi', DHT_server.TWISTED_PORT, factory)
    return factory.done



if __name__ == '__main__':
    task.react(main)