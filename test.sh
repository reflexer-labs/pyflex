#!/bin/bash

CONFIG="testchain-value-fixed-discount-governance-median-multisig"
#TEST_FILE=""
while getopts :c:f: option
do
case "${option}"
in
c) CONFIG=${OPTARG};;
f) TEST_FILE=${OPTARG};;
esac
done
<< END

CONFIG=$1
if [ -z "$CONFIG" ]
then
    echo "No config specified. ie. 'test.sh testchain-value-fixed-discount-governance-median-multisig'"
    CONFIG="testchain-value-fixed-discount-governance-median-multisig"
    echo "Defaulting to ${CONFIG}"
fi
# Optional specify test file to test. Otherwise, run all tests
TEST_FILE=$2
END

# Pull the docker image
docker pull reflexer/testchain-pyflex:${CONFIG}

# Remove existing container if tests not gracefully stopped
docker-compose -f ${CONFIG}.yml down

# Start ganache
docker-compose -f ${CONFIG}.yml up -d ganache

# Start parity and wait to initialize
docker-compose -f ${CONFIG}.yml up -d parity
sleep 2

#Run the tests

py.test -s --cov=pyflex --cov-report=term --cov-append tests/${TEST_FILE}
TEST_RESULT=$?

# Cleanup
docker-compose -f ${CONFIG}.yml down

exit $TEST_RESULT
