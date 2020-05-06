import os
import time
import argparse
import config.config as config
import torch.multiprocessing as mp

from environment.PuzzleN import PuzzleN
from networks.puzzleNet import PuzzleNet
import torch

from training import trainUtils
import torch

from tensorboardX import SummaryWriter

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config", required=True, help="Path of Config File", type=str
    )

    args = parser.parse_args()

    conf = config.Config(args.config)

    env = PuzzleN(conf.puzzleSize)

    name = conf.trainName()

    writer = SummaryWriter(comment="-" + name)
    savePath = os.path.join("saves", name) + ".pt"

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    numGPUs = torch.cuda.device_count()

    net = Net(conf.puzzleSize + 1)
    targetNet = Net(conf.puzzleSize + 1)

    if numGPUs > 1:
        net = torch.nn.DataParallel(net)

    print("Using %d GPU(s)" % numGPUs)

    net.to(device)
    targetNet.to(device)

    for targetParam, param in zip(net.parameters(), targetNet.parameters()):
        targetParam.data.copy_(param)

    numWorkers = conf.numWorkers
    numProcs = conf.numProcs

    optimizer = torch.optim.Adam(net.parameters(), lr=conf.lr)
    numEpochs = conf.numEpochs
    tau = conf.tau

    lossLogger = []

    startTrainTime = time.time()

    for epoch in range(1, numEpochs + 1):

        genProcesses = []
        genQueue = mp.Queue()

        startGenTime = time.time()

        for _ in range(numProcs):
            p = mp.Process(
                target=trainUtils.makeTrainingData,
                args=(
                    env,
                    targetNet,
                    device,
                    conf.numberOfScrambles // numProcs,
                    conf.scrambleDepth,
                    genQueue,
                ),
            )
            genProcesses.append(p)
            p.start()

        scrambles = []
        targets = []
        procsFinished = 0

        while procsFinished < numProcs:
            if not genQueue.empty():
                scrambleSet, targetSet = genQueue.get()
                scrambles.append(scrambleSet)
                targets.append(targetSet)
                procsFinished += 1

        for p in genProcesses:
            p.join()

        scrambles = torch.cat(scrambles)
        targets = torch.cat(targets)

        # scrambles, targets = trainUtils.makeTrainingData(
        #     env, targetNet, device, conf.numberOfScrambles, conf.scrambleDepth
        # )

        genTime = time.time() - startGenTime

        print("Generation time is %.3f seconds" % genTime)

        scramblesDataSet = trainUtils.Puzzle15DataSet(scrambles, targets)

        trainLoader = torch.utils.data.DataLoader(
            scramblesDataSet,
            batch_size=conf.batchSize,
            shuffle=True,
            num_workers=numWorkers,
        )

        avgLoss, lossLogger = trainUtils.train(
            net, device, trainLoader, optimizer, lossLogger
        )

        for targetParam, param in zip(targetNet.parameters(), net.parameters()):
            targetParam.data.copy_(tau * param + (1 - tau) * targetParam)

        print("Epoch: %d/%d" % (epoch, numEpochs))

        if epoch % 10 == 0:
            print("Saving Model")
            torch.save(net.state_dict(), savePath)

    trainTime = time.time() - startTrainTime

    print(
        "Training Time is %i hours, %i minutes and %i seconds"
        % (trainTime / 3600, trainTime / 60 % 60, trainTime % 60)
    )
