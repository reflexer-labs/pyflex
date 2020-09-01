#!/bin/bash

# Pull the docker image
docker pull reflexer/testchain-pyflex:unit-testing-testchain-value-fixed-discount-governance-median-multisig
#docker pull reflexer/testchain-pyflex:unit-testing-testchain-value-english-governance-median-vote-quorum
#docker pull reflexer/testchain-pyflex:unit-testing-testchain-value-english-governance-median-multisig#
#docker pull reflexer/testchain-pyflex:unit-testing-testchain-value-fixed-discount-uniswap-vote-quorum
#docker pull reflexer/testchain-pyflex:unit-testing-testchain-value-fixed-discount-uniswap-multisig

# Remove existing container if tests not gracefully stopped
docker-compose down

# Start ganache
docker-compose up -d ganache

# Start parity and wait to initialize
docker-compose up -d parity
sleep 2

#Run the tests

py.test -s --cov=pyflex --cov-report=term --cov-append tests/$@
TEST_RESULT=$?

# Cleanup
docker-compose down

exit $TEST_RESULT
