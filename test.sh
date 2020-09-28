#!/bin/bash

CONFIG="testchain-value-fixed-discount-governance-median-multisig-basic"
while getopts :c:f: option
do
case "${option}"
in
c) CONFIG=${OPTARG};;
f) TEST_FILE=${OPTARG};;
esac
done

# Pull the docker image
docker pull reflexer/testchain-pyflex:${CONFIG}

# Remove existing container if tests not gracefully stopped
docker-compose -f config/${CONFIG}.yml down

# Start ganache
docker-compose -f config/${CONFIG}.yml up -d ganache

# Start parity and wait to initialize
docker-compose -f config/${CONFIG}.yml up -d parity
sleep 2

#Run the tests

py.test -s --cov=pyflex --cov-report=term --cov-append tests/${TEST_FILE}
TEST_RESULT=$?

# Cleanup
docker-compose -f config/${CONFIG}.yml down

exit $TEST_RESULT
