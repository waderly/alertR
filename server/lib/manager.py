#!/usr/bin/python2

# written by sqall
# twitter: https://twitter.com/sqall01
# blog: http://blog.h4des.org
# github: https://github.com/sqall01
#
# Licensed under the GNU Public License, version 2.

import threading
import os
import time
import logging
import collections
from server import AsynchronousSender


# this class is woken up if a sensor alert or state change is received
# and sends updates to all manager clients
class ManagerUpdateExecuter(threading.Thread):

	def __init__(self, globalData):
		threading.Thread.__init__(self)

		# get global configured data
		self.globalData = globalData
		self.serverSessions = self.globalData.serverSessions
		self.managerUpdateInterval = self.globalData.managerUpdateInterval
		self.storage = self.globalData.storage

		# file nme of this file (used for logging)
		self.fileName = os.path.basename(__file__)

		# create an event that is used to wake this thread up
		# and reacte on state changes/sensor alerts
		self.managerUpdateEvent = threading.Event()
		self.managerUpdateEvent.clear()

		# set exit flag as false
		self.exitFlag = False

		# this is used to know when the last status update was send to the
		# manager clients
		self.lastStatusUpdateSend = 0

		# this is used to know if a full status update has to be sent to
		# the manager clients (ignoring the time interval)
		self.forceStatusUpdate = False

		# this is a queue that is used to signalize the state changes
		# that should be sent to the manager clients
		self.queueStateChange = collections.deque()

		# this is the last known state if the alert system is activated
		# (needed when the database is changed directly for example
		# via the mobile manager app)
		self.lastAlertSystemActiveState = False


	def run(self):

		while 1:

			# check if thread should terminate
			if self.exitFlag:
				return

			# check if state change queue is empty before waiting
			# for event (or timeout)
			if len(self.queueStateChange) == 0:
				# wait 2 of seconds before checking if sending a
				# status update to all manager nodes or check it when
				# the event is triggered
				self.managerUpdateEvent.wait(2)
				self.managerUpdateEvent.clear()

			# get current state of the alert system (active or not)
			alertSystemActiveState = self.storage.isAlertSystemActive()

			# check if last status update has timed out
			# or a new manager has connected
			# or the last known alert system active state is not
			# the same as the current alert system active state
			# (this can happen when the database is changed directly
			# for example via the mobile manager app)
			# => send status update to all manager
			if (((int(time.time()) - self.managerUpdateInterval)
				> self.lastStatusUpdateSend)
				or self.forceStatusUpdate
				or self.lastAlertSystemActiveState 
				!= alertSystemActiveState):

				# check if the current alert system active state is not the
				# same as the last known
				# (this can happen when the database is changed directly
				# for example via the mobile manager app)
				# => send alerts off to all alert clients
				if (alertSystemActiveState != self.lastAlertSystemActiveState
					and alertSystemActiveState == 0):
					for serverSession in self.serverSessions:
						# ignore sessions which do not exist yet
						# and that are not managers
						if serverSession.clientComm == None:
							continue
						if serverSession.clientComm.nodeType != "alert":
							continue
						if not serverSession.clientComm.clientInitialized:
							continue

						# sending sensor alerts off to alert client
						# via a thread to not block this one
						sensorAlertsOffProcess = AsynchronousSender(
							self.globalData, serverSession.clientComm)
						# set thread to daemon
						# => threads terminates when main thread terminates	
						sensorAlertsOffProcess.daemon = True
						sensorAlertsOffProcess.sendAlertSensorAlertsOff = True
						logging.debug("[%s]: Sending sensor " % self.fileName
							+ "alerts off to alert client (%s:%d)."
							% (serverSession.clientComm.clientAddress,
							serverSession.clientComm.clientPort))
						sensorAlertsOffProcess.start()

				# update time when last status update was sent
				self.lastStatusUpdateSend = int(time.time())

				# reset new client variable
				self.forceStatusUpdate = False

				# update the alert system active state with the
				# state during this update
				# (is needed if the database is changed directly
				# for example via the mobile manager app)
				self.lastAlertSystemActiveState = alertSystemActiveState

				# empty current state queue
				# (because the state changes are also transmitted
				# during the full state update)
				self.queueStateChange.clear()

				for serverSession in self.serverSessions:
					# ignore sessions which do not exist yet
					# and that are not managers
					if serverSession.clientComm == None:
						continue
					if serverSession.clientComm.nodeType != "manager":
						continue
					if not serverSession.clientComm.clientInitialized:
						continue

					# sending status update to manager via a thread
					# to not block the manager update executer
					statusUpdateProcess = AsynchronousSender(self.globalData,
						serverSession.clientComm)
					# set thread to daemon
					# => threads terminates when main thread terminates	
					statusUpdateProcess.daemon = True
					statusUpdateProcess.sendManagerUpdate = True
					statusUpdateProcess.start()

				# if status update was sent to manager clients
				# => ignore state changes (because they are also covered
				# by a status update)
				continue

			# if status change queue is not empty
			# => send status changes to manager clients
			while len(self.queueStateChange) != 0:
				sensorId = self.queueStateChange.popleft()

				for serverSession in self.serverSessions:
					# ignore sessions which do not exist yet
					# and that are not managers
					if serverSession.clientComm == None:
						continue
					if serverSession.clientComm.nodeType != "manager":
						continue
					if not serverSession.clientComm.clientInitialized:
						continue

					# sending status update to manager via a thread
					# to not block the manager update executer
					stateChangeProcess = AsynchronousSender(self.globalData,
						serverSession.clientComm)
					# set thread to daemon
					# => threads terminates when main thread terminates	
					stateChangeProcess.daemon = True
					stateChangeProcess.sendManagerStateChange = True
					stateChangeProcess.sendManagerStateChangeSensorId \
						= sensorId
					stateChangeProcess.start()


	# sets the exit flag to shut down the thread
	def exit(self):
		self.exitFlag = True
		return