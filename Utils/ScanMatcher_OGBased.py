import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from Utils.OccupancyGrid import OccupancyGrid
from scipy.ndimage import gaussian_filter

class ScanMatcher:
    def __init__(self, og, searchRadius, searchHalfRad, scanSigmaInNumGrid, coarseFactor):
        self.searchRadius = searchRadius
        self.searchHalfRad = searchHalfRad
        self.og = og
        self.scanSigmaInNumGrid = scanSigmaInNumGrid
        self.lastScan = [] # 2D point clouds [px, py]
        self.coarseFactor = coarseFactor

    def frameSearchSpace(self, estimatedX, estimatedY, unitLength, sigma):
        maxScanRadius = 1.1 * self.og.lidarMaxRange + self.searchRadius
        xRangeList = [estimatedX - maxScanRadius, estimatedX + maxScanRadius]
        yRangeList = [estimatedY - maxScanRadius, estimatedY + maxScanRadius]
        idxEndX, idxEndY = int((xRangeList[1] - xRangeList[0]) / unitLength),  int((yRangeList[1] - yRangeList[0]) / unitLength)
        searchSpace = np.zeros((idxEndY + 1, idxEndX + 1))

        self.og.checkAndExapndOG(xRangeList, yRangeList)
        xRangeListIdx, yRangeListIdx = self.og.convertRealXYToMapIdx(xRangeList, yRangeList)
        ogMap = self.og.occupancyGridVisited[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]] /\
                      self.og.occupancyGridTotal[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]]
        ogMap = ogMap > 0.5
        ogX = self.og.OccupancyGridX[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]]
        ogY = self.og.OccupancyGridY[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]]

        ogX, ogY = ogX[ogMap], ogY[ogMap]
        ogIdx = self.convertXYToSearchSpaceIdx(ogX, ogY, xRangeList[0], yRangeList[0], unitLength)
        searchSpace[ogIdx[1], ogIdx[0]] = 1
        #lastScanIdx = self.convertXYToSearchSpaceIdx(self.lastScan[0], self.lastScan[1], xRangeList[0], yRangeList[0], unitLength)
        #searchSpace[lastScanIdx[1], lastScanIdx[0]] = 1
        probSP = self.generateProbSearchSpace(searchSpace, sigma)
        return xRangeList, yRangeList, probSP

    def generateProbSearchSpace(self, searchSpace, sigma):
        probSP = gaussian_filter(searchSpace, sigma=sigma)
        maxCap = 1 / (2 * np.pi * sigma ** 2)
        probSP[probSP > maxCap] = maxCap
        probSP = probSP / maxCap
        return probSP

    def matchScan(self, reading, count):
        """Iteratively find the best dx, dy and dtheta"""
        estimatedX, estimatedY, estimatedTheta, rMeasure = reading['x'], reading['y'], reading['theta'], reading['range']
        rMeasure = np.asarray(rMeasure)
        if self.lastScan == []:
            px, py = self.covertMeasureToXY(estimatedX, estimatedY, estimatedTheta, rMeasure)
            self.lastScan = [px, py]
            return reading
        # Coarse Search
        courseSearchStep = self.coarseFactor * self.og.unitGridSize  # make this even number of unitGridSize for performance
        coarseSigma = self.scanSigmaInNumGrid / self.coarseFactor
        xRangeList, yRangeList, probSP = self.frameSearchSpace(estimatedX, estimatedY, courseSearchStep, coarseSigma)
        matchedPx, matchedPy, matchedReading = self.searchToMatch(
            probSP, estimatedX, estimatedY, estimatedTheta, rMeasure, xRangeList, yRangeList, self.searchRadius, self.searchHalfRad, courseSearchStep)
        #########   For Debug Only  #############
        #if count > 39:
        #    self.plotMatchOverlay(probSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, courseSearchStep)
        #########################################
        # Fine Search
        fineSearchStep = self.og.unitGridSize
        fineSigma = self.scanSigmaInNumGrid
        fineSearchHalfRad = self.searchHalfRad
        xRangeList, yRangeList, probSP = self.frameSearchSpace(matchedReading['x'], matchedReading['y'], fineSearchStep, fineSigma)
        matchedPx, matchedPy, matchedReading = self.searchToMatch(
            probSP, matchedReading['x'], matchedReading['y'], matchedReading['theta'], matchedReading['range'], xRangeList, yRangeList, courseSearchStep, fineSearchHalfRad, fineSearchStep)
        self.lastScan = [matchedPx, matchedPy]
        #########   For Debug Only  #############
        if count > 57:
            self.plotMatchOverlay(probSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, fineSearchStep)
        #########################################
        return matchedReading

    def covertMeasureToXY(self, estimatedX, estimatedY, estimatedTheta, rMeasure):
        rads = np.linspace(estimatedTheta - self.og.lidarFOV / 2, estimatedTheta + self.og.lidarFOV / 2,
                           num=self.og.numSamplesPerRev)
        range_idx = rMeasure < self.og.lidarMaxRange
        rMeasureInRange = rMeasure[range_idx]
        rads = rads[range_idx]
        px = estimatedX + np.cos(rads) * rMeasureInRange
        py = estimatedY + np.sin(rads) * rMeasureInRange
        return px, py

    def searchToMatch(self, probSP, estimatedX, estimatedY, estimatedTheta, rMeasure, xRangeList, yRangeList, searchRadius, searchHalfRad, unitLength):
        px, py = self.covertMeasureToXY(estimatedX, estimatedY, estimatedTheta, rMeasure)
        numCellOfSearchRadius  = int(searchRadius / unitLength)
        xMovingRange = np.arange(-numCellOfSearchRadius, numCellOfSearchRadius + 1)
        yMovingRange = np.arange(-numCellOfSearchRadius, numCellOfSearchRadius + 1)
        xv, yv = np.meshgrid(xMovingRange, yMovingRange)
        xv = xv.reshape((xv.shape[0], xv.shape[1], 1))
        yv = yv.reshape((yv.shape[0], yv.shape[1], 1))
        maxMatchScore, maxIdx = 0, None
        for theta in np.arange(-searchHalfRad, searchHalfRad + self.og.angularStep, self.og.angularStep):
            rotatedPx, rotatedPy = self.rotate((estimatedX, estimatedY), (px, py), theta)
            rotatedPxIdx, rotatedPyIdx = self.convertXYToSearchSpaceIdx(rotatedPx, rotatedPy, xRangeList[0], yRangeList[0], unitLength)
            uniqueRotatedPxPyIdx = np.unique(np.column_stack((rotatedPxIdx, rotatedPyIdx)), axis=0)
            rotatedPxIdx, rotatedPyIdx = uniqueRotatedPxPyIdx[:, 0], uniqueRotatedPxPyIdx[:, 1]
            #########   For Debug Only  #############
            #self.plotMatchOverlay(probSP, rotatedPx, rotatedPy, xRangeList, yRangeList, unitLength)
            #########################################
            rotatedPxIdx = rotatedPxIdx.reshape(1, 1, -1)
            rotatedPyIdx = rotatedPyIdx.reshape(1, 1, -1)
            rotatedPxIdx = rotatedPxIdx + xv
            rotatedPyIdx = rotatedPyIdx + yv
            convResult = probSP[rotatedPyIdx, rotatedPxIdx]
            convResultSum = np.sum(convResult, axis=2)
            if convResultSum.max() > maxMatchScore:
                maxMatchScore = convResultSum.max()
                maxIdx = np.unravel_index(convResultSum.argmax(), convResultSum.shape)
                dTheta = theta
                #########   For Debug Only  #############
                # matchedPx, matchedPy = self.rotate((estimatedX, estimatedY), (px, py), dTheta)
                # dx, dy = xMovingRange[maxIdx[1]] * unitLength, yMovingRange[maxIdx[0]] * unitLength
                # self.plotMatchOverlay(probSP, matchedPx + dx, matchedPy + dy, xRangeList, yRangeList, unitLength)
                #########################################
        if maxIdx is None:
            dx, dy, dtheta = 0, 0, 0
        else:
            dx, dy = xMovingRange[maxIdx[1]] * unitLength, yMovingRange[maxIdx[0]] * unitLength
        matchedReading = {"x": estimatedX + dx, "y": estimatedY + dy, "theta": estimatedTheta + dTheta,
                          "range": rMeasure}
        matchedPx, matchedPy = self.rotate((estimatedX, estimatedY), (px, py), dTheta)
        return matchedPx + dx, matchedPy + dy, matchedReading

    def plotMatchOverlay(self, probSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, unitLength):
        plt.figure(figsize=(19.20, 19.20))
        plt.imshow(probSP, origin='lower')
        pxIdx, pyIdx = self.convertXYToSearchSpaceIdx(matchedPx, matchedPy, xRangeList[0], yRangeList[0], unitLength)
        plt.scatter(pxIdx, pyIdx, c='r', s=5)
        poseXIdx, poseYIdx = self.convertXYToSearchSpaceIdx(matchedReading['x'], matchedReading['y'], xRangeList[0], yRangeList[0], unitLength)
        plt.scatter(poseXIdx, poseYIdx, color='blue', s=50)
        plt.show()

    def rotate(self, origin, point, angle):
        """
        Rotate a point counterclockwise by a given angle around a given origin.

        The angle should be given in radians.
        """
        ox, oy = origin
        px, py = point
        qx = ox + np.cos(angle) * (px - ox) - np.sin(angle) * (py - oy)
        qy = oy + np.sin(angle) * (px - ox) + np.cos(angle) * (py - oy)
        return qx, qy

    def convertXYToSearchSpaceIdx(self, px, py, beginX, beginY, unitLength):
        xIdx = (((px - beginX) / unitLength)).astype(int)
        yIdx = (((py - beginY) / unitLength)).astype(int)
        return xIdx, yIdx

def updateEstimatedPose(currentRawReading, previousMatchedReading, previousRawReading):
    estimatedX = previousMatchedReading['x'] + currentRawReading['x'] - previousRawReading['x']
    estimatedY = previousMatchedReading['y'] + currentRawReading['y'] - previousRawReading['y']
    estimatedTheta = previousMatchedReading['theta'] + currentRawReading['theta'] - previousRawReading['theta']
    estimatedReading = {'x': estimatedX, 'y': estimatedY, 'theta': estimatedTheta, 'range': currentRawReading['range']}
    return estimatedReading

def updateTrajectoryPlot(matchedReading, xTrajectory, yTrajectory, colors, count):
    x, y, theta, range = matchedReading['x'], matchedReading['y'], matchedReading['theta'], matchedReading['range']
    xTrajectory.append(x)
    yTrajectory.append(y)
    if count % 1 == 0:
        plt.scatter(x, y, color=next(colors), s=35)

def processSensorData(sensorData, og, sm, plotTrajectory = True):
    count = 0
    plt.figure(figsize=(19.20, 19.20))
    colors = iter(cm.rainbow(np.linspace(1, 0, len(sensorData) + 1)))
    xTrajectory, yTrajectory = [], []
    for key in sorted(sensorData.keys()):
        count += 1
        print(count)
        if count == 1:
            og.updateOccupancyGrid(sensorData[key])
            previousMatchedReading = sensorData[key]
            previousRawReading = sensorData[key]
        estimatedReading = updateEstimatedPose(sensorData[key], previousMatchedReading, previousRawReading)
        matchedReading = sm.matchScan(estimatedReading, count)
        og.updateOccupancyGrid(matchedReading)
        # og.plotOccupancyGrid(plotThreshold=False)
        previousMatchedReading = matchedReading
        previousRawReading = sensorData[key]

        if count == 100:
            break
        if plotTrajectory:
            updateTrajectoryPlot(matchedReading, xTrajectory, yTrajectory, colors, count)
    plt.scatter(xTrajectory[0], yTrajectory[0], color='r', s=500)
    plt.scatter(xTrajectory[-1], yTrajectory[-1], color=next(colors), s=500)
    plt.plot(xTrajectory, yTrajectory)
    og.plotOccupancyGrid(plotThreshold=False)

def main():
    initMapXLength, initMapYLength, unitGridSize, lidarFOV, lidarMaxRange = 10, 10, 0.02, np.pi, 10 # in Meters
    scanMatchSearchRadius, scanMatchSearchHalfRad, scanSigmaInNumGrid, coarseFactor = 2.2, 0.35, 2, 10 # 0.35 is 20deg
    wallThickness = 5 * unitGridSize
    jsonFile = "../DataSet/PreprocessedData/intel_gfs"
    with open(jsonFile, 'r') as f:
        input = json.load(f)
        sensorData = input['map']
    numSamplesPerRev = len(sensorData[list(sensorData)[0]]['range'])  # Get how many points per revolution
    spokesStartIdx = int(0) # theta= 0 is x direction. spokes=0 is -y direction, the first ray of lidar scan direction. spokes increase counter-clockwise
    og = OccupancyGrid(initMapXLength, initMapYLength, unitGridSize, lidarFOV, numSamplesPerRev, lidarMaxRange, wallThickness, spokesStartIdx)
    sm = ScanMatcher(og, scanMatchSearchRadius, scanMatchSearchHalfRad, scanSigmaInNumGrid, coarseFactor)
    processSensorData(sensorData, og, sm, plotTrajectory=False)

if __name__ == '__main__':
    main()