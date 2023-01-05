import netsquid as ns
import pydynaa
from netsquid.nodes import Node, Network
from netsquid.components import QuantumMemory
from netsquid.nodes.connections import DirectConnection
import random as rd
from netsquid.qubits.qubitapi import *
from netsquid.protocols import NodeProtocol, Signals
import numpy as np
from netsquid.components.models import FibreDelayModel, FibreLossModel, DepolarNoiseModel, FixedDelayModel
from netsquid.components.cqchannel import CombinedChannel
from pydynaa.core import SimulationEngine
from matplotlib import pyplot as plt
import numpy as np


class AliceProtocol(NodeProtocol):

    n = 10000

    def __init__(self, node, port_1, channel):
        """
        :type port_2: object
        """
        super().__init__(node)
        self.port_name = port_1
        self.connected_channel = channel
        self.matching_keybits = None
        self.send_evtype = pydynaa.EventType("Send", "Send the prepared qubit")
        self.time_stamp = []
        self.binary_key = {}
        self.alice_basis = {}
        self.delay = 1
        self.time_stamp_label = "TIME_STAMP"
        self.add_signal(self.time_stamp_label,
                        event_type=pydynaa.EventType("The final time stamp", "The final time stamp to be sent"))
        self.add_signal("QUBITS_DONE", event_type=pydynaa.EventType("The Qubits done","The qubits generation is finished"))

    def _Assign_Quantum_State(self, qubit):
        if rd.randint(1, 2) == 1:
            basis = "|Z >"
            if rd.randint(0, 1) == 0:
                assign_qstate(qubit, ns.qubits.ketstates.s0)
                binary = 0
            else:
                assign_qstate(qubit, ns.qubits.ketstates.s1)
                binary = 1
        else:
            basis = "|X >"
            if rd.randint(0, 1) == 0:
                assign_qstate(qubit, ns.qubits.ketstates.h0)
                binary = 0
            else:
                assign_qstate(qubit, ns.qubits.ketstates.h1)
                binary = 1

        return (qubit, basis, binary)

    def _create_qubit(self, event):
        qubit = create_qubits(num_qubits=1, system_name="Q")
        q, basis, binary = self._Assign_Quantum_State(qubit)
        self.time_stamp.append(ns.sim_time())
        self.alice_basis[ns.sim_time()] = basis
        self.binary_key[ns.sim_time()] = binary
        self.node.ports[self.port_name].tx_output((None, q))

    def run(self):
        port_qout_bob = self.node.ports[self.port_name]
        sim_engine = SimulationEngine()
        qubit_create = pydynaa.EventHandler(self._create_qubit)
        for i in range(n):
            self._schedule_after(i * self.delay, self.send_evtype)
            self._wait(qubit_create, entity=self, event_type=self.send_evtype)

        yield self.await_signal(self.receiver_protocol, Signals.READY)
        yield self.await_port_input(port_qout_bob)
        [(Bob_Basis, _)] = port_qout_bob.rx_input().items
        bob_basis = {
            keys - self.connected_channel.models['delay_model'].generate_delay(**{'length': self.connected_channel.properties['length']}): Bob_Basis[keys] for keys in Bob_Basis}
        exact_basis = {k: self.alice_basis[k] for k in self.alice_basis if
                       k in bob_basis and self.alice_basis[k] == bob_basis[k]}
        matching_time_stamps = [
            key + self.connected_channel.models['delay_model'].generate_delay(**{'length': self.connected_channel.properties['length']}) for key in
            exact_basis]
        self.matching_keybits = {key: self.binary_key.get(key) for key in exact_basis}
        self.send_signal(self.time_stamp_label)
        port_qout_bob.tx_output((matching_time_stamps, None))

class BobProtocol(NodeProtocol):

    n = 10000

    def __init__(self, node, port_1):
        super().__init__(node=node)
        self.port_name = port_1
        self.list_length = None
        self.binary_key = None
        self.bob_basis = None
        self.matching_keybits = None
        self.recv_evtype = None
        self.bob_time_stamp = None
        self.bob_signal_label = "BASIS_READY"
        self.add_signal("BASIS_READY", event_type=pydynaa.EventType("The Bob's basis", "The Bob's basis are ready"))
        self.add_signal("KEY_ESTABLISHED", event_type=pydynaa.EventType("ESTABLISHED!!","The key is established"))

    def _Measure_Quantum_State(self, node, qubit, i):

        if qubit is None:
            return ("None", "None")
        else:
            node.qmemory.put(qubit, positions=i)
            if rd.randint(1, 2) == 1:
                basis = "|Z >"
                [m], _ = node.qmemory.measure(positions=[i], observable=ns.Z)
                bin_key = m
            else:
                basis = "|X >"
                [m], _ = node.qmemory.measure(positions=[i], observable=ns.X)
                bin_key = m

            return (basis, bin_key)

    def _send_basis(self,event):
        self.send_signal(Signals.READY)
        self.node.ports[self.port_name].tx_output((self.bob_basis, None))

    def run(self):
        port_qin_alice = self.node.ports[self.port_name]
        sim_engine = SimulationEngine()
        recv_evt = pydynaa.EventType("Recieve qubit", "Recieve the prepared qubit")
        self.recv_evtype = recv_evt
        recv_evexpr = pydynaa.EventExpression(source=self, event_type=self.recv_evtype)
        wait_evexpr = self.await_port_input(port_qin_alice)
        time_stamp = []
        basis = {}
        bin_key = {}
        i = 0
        while i < n:
            evexpr = yield wait_evexpr
            #print("wait event expression yielded")
            if evexpr.value:
                [(_, [key])] = port_qin_alice.rx_input().items
                #print("item received")
                basis[sim_engine.current_time], bin_key[sim_engine.current_time] = self._Measure_Quantum_State(self.node, key,
                                                                                                         i)
                time_stamp.append(sim_engine.current_time)
                i = i + 1
                #print(sim_engine.current_time)
                self._schedule_at(sim_engine.current_time + i, self.recv_evtype)
            else:
                #print("item not recieved")
                i = i + 1
                #print(sim_engine.current_time)
                self._schedule_at(sim_engine.current_time + i, self.recv_evtype)

        self.bob_basis = {key: basis[key] for key in basis if basis[key] != "None"}
        self.binary_key = {key: bin_key[key] for key in bin_key if bin_key[key] != "None"}
        self.bob_time_stamp = time_stamp
        evtype_1 = pydynaa.EventType("Send Basis","Send the list of basis")
        evhandler_1 = pydynaa.EventHandler(self._send_basis)
        self._schedule_now(evtype_1)
        self._wait(evhandler_1,self,evtype_1)
        #port_qin_alice.tx_output((self.bob_basis, None))
        for position in self.node.qmemory.used_positions:
            self.node.qmemory.discard(position)

        yield self.await_signal(self.sender_protocol, self.sender_protocol.time_stamp_label)
        yield self.await_port_input(port_qin_alice)
        [(matching_time_stamp,_)] = port_qin_alice.rx_input().items
        self.matching_keybits = {key: self.binary_key[key] for key in matching_time_stamp}
        self.list_length = len(self.matching_keybits)
        self.send_signal("KEY_ESTABLISHED")


def protocol(a):
    alice_qmemory = QuantumMemory("Alice_Memory", num_positions=n, models={'delay_model': FixedDelayModel(1)})
    bob_qmemory = QuantumMemory("Bob_Memory", num_positions=n, models={"delay_model": FixedDelayModel(1)})

    alice = Node("Alice", qmemory=alice_qmemory, port_names=["qout_bob", "cin_bob"])
    bob = Node("Bob", qmemory=bob_qmemory,  port_names=["qin_alice", "cout_alice"])
   
    channel_a2b = CombinedChannel("QC_Channel_a2b", length=100, models={"delay_model": FibreDelayModel(), "quantum_loss_model": FibreLossModel(p_loss_init=0, p_loss_length=0.2), "quantum_noise_model": DepolarNoiseModel(depolar_rate=100*a, time_independent=False)}, transmit_empty_items=True)
    channel_b2a = CombinedChannel("QC_Channel_b2a", length=100, models={"delay_model": FibreDelayModel(), "quantum_loss_model": FibreLossModel(p_loss_init=0, p_loss_length=0.2), "quantum_noise_model": DepolarNoiseModel(depolar_rate=100*a, time_independent=False)}, transmit_empty_items=True)
    connect = DirectConnection("Connection",channel_AtoB=channel_a2b,channel_BtoA=channel_b2a)

    network = Network(name="Network")
    network.add_nodes([alice, bob])
    network.add_connection(alice, bob, connection=connect, label="quantum", port_name_node1="qout_bob", port_name_node2="qin_alice")

    alice_protocol = AliceProtocol(alice, "qout_bob", channel_a2b)
    bob_protocol = BobProtocol(bob, "qin_alice")

    alice_protocol.receiver_protocol = bob_protocol
    bob_protocol.sender_protocol = alice_protocol

    
    for j in range(1):
        ns.sim_reset()
        alice_protocol.start()
        bob_protocol.start()
        stats = ns.sim_run()
        list_length = getattr(bob_protocol, 'list_length')
        alice_matching_key = getattr(alice_protocol, 'matching_keybits')
        bob_matching_key = getattr(bob_protocol, 'matching_keybits')
        alice_key = [value for value in alice_matching_key.values()]
        bob_key = [value for value in bob_matching_key.values()]
        error_bits = list(map(lambda x, y: x ^ y, alice_key, bob_key))
        key_bit_error[a] = (np.sum(error_bits) / list_length)
        
    print(f"The time required to establish the key is {ns.sim_time()}\n\n")
    print(f"The matched key according to Alice  is:\n\n {alice_matching_key}\n\n")
    print(f"The matched key according to bob  is:\n\n {bob_matching_key}\n\n") 
    print(f"The matched key according to Alice  is:\n\n {alice_key}\n\n")
    print(f"The matched key according to Alice  is:\n\n {bob_key}\n\n")
    print(f"The key bit error for an iteration. is:\n\n {key_bit_error}\n\n")


n = 10000
#standard model: 100  0.2  1e3

#for i in range 
if __name__ == "__main__":
	x = np.ones(36)
	global key_bit_error
	key_bit_error = np.ones(36)
	for a in range(36):
		protocol(a)
		x[a] = a
	
	plt.title("Key bit error : Depolar Noise Model")
	plt.xlabel("depolar rate")
	plt.ylabel("Key bit error rate")
	plt.plot(x*100, key_bit_error)
	plt.show()
	
    
