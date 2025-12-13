"""Test check_pending_request query behavior with optional resource_id.

Usage:
    uv run python -m devscripts.test_check_pending
"""

import gel


def main() -> None:
    """Test the check_pending_request query with and without resource_id."""
    client = gel.create_client()

    telegram_id = 335036699
    resource_type = 'access_identity'
    status = 'pending'

    print('=' * 60)
    print('Testing check_pending_request query')
    print('=' * 60)
    print(f'Parameters:')
    print(f'  telegram_id: {telegram_id}')
    print(f'  resource_type: {resource_type}')
    print(f'  status: {status}')
    print()

    # Test 1: Fixed query with coalesce pattern
    print('Test 1: Fixed query (coalesce pattern) WITHOUT resource_id (should be True)')
    print('-' * 60)

    fixed_query = """\
        select exists (
            select AuthorizationRequest
            filter
                .user.telegram_id = <int64>$telegram_id
                and .resource_type = <ResourceType>$resource_type
                and .status = <optional AuthStatus>$status ?? AuthStatus.pending
                and (
                    <optional str>$resource_id ?? '' = ''
                    or .resource_id = <optional str>$resource_id
                )
        )"""

    result = client.query_single(
        fixed_query,
        telegram_id=telegram_id,
        resource_type=resource_type,
        status=status,
        resource_id=None,
    )
    print(f'Result: {result}')
    print()

    # Test 2: Fixed query using WITH block - without resource_id
    print('Test 2: Fixed query (WITH + not exists) WITHOUT resource_id (should be True)')
    print('-' * 60)

    fixed_query_not_exists = """\
        with
            resource_id := <optional str>$resource_id
        select exists (
            select AuthorizationRequest
            filter
                .user.telegram_id = <int64>$telegram_id
                and .resource_type = <ResourceType>$resource_type
                and .status = <optional AuthStatus>$status ?? AuthStatus.pending
                and (
                    not exists resource_id
                    or .resource_id = resource_id
                )
        )"""

    result = client.query_single(
        fixed_query_not_exists,
        telegram_id=telegram_id,
        resource_type=resource_type,
        status=status,
        resource_id=None,
    )
    print(f'Result: {result}')
    print()

    # Test 2b: Fixed query using ?= coalescent equality - without resource_id
    print('Test 2b: Fixed query (?= operator) WITHOUT resource_id (should be True)')
    print('-' * 60)

    fixed_query = """\
        with
            resource_id := <optional str>$resource_id
        select exists (
            select AuthorizationRequest
            filter
                .user.telegram_id = <int64>$telegram_id
                and .resource_type = <ResourceType>$resource_type
                and .status = <optional AuthStatus>$status ?? AuthStatus.pending
                and .resource_id ?= resource_id
        )"""

    result = client.query_single(
        fixed_query,
        telegram_id=telegram_id,
        resource_type=resource_type,
        status=status,
        resource_id=None,
    )
    print(f'Result: {result}')
    print()

    # Test 2c: Try omitting resource_id parameter entirely
    print('Test 2c: Fixed query (?=) OMITTING resource_id param (should be True)')
    print('-' * 60)

    # Query without $resource_id parameter - use empty set literal
    fixed_query_no_param = """\
        with
            resource_id := <optional str>{}
        select exists (
            select AuthorizationRequest
            filter
                .user.telegram_id = <int64>$telegram_id
                and .resource_type = <ResourceType>$resource_type
                and .status = <optional AuthStatus>$status ?? AuthStatus.pending
                and .resource_id ?= resource_id
        )"""

    result = client.query_single(
        fixed_query_no_param,
        telegram_id=telegram_id,
        resource_type=resource_type,
        status=status,
    )
    print(f'Result: {result}')
    print()

    # Test 2d: Debug ?= behavior directly
    print('Test 2d: Debug ?= with empty set directly')
    print('-' * 60)

    debug_query = """\
        with
            resource_id := <optional str>{}
        select {
            resource_id_value := resource_id,
            resource_id_exists := exists resource_id,
            test_str := 'hello',
            hello_eq_empty := 'hello' ?= resource_id
        }"""

    result = client.query_single(debug_query)
    print(f'resource_id_value: {result.resource_id_value}')
    print(f'resource_id_exists: {result.resource_id_exists}')
    print(f'test_str: {result.test_str}')
    print(f'hello ?= resource_id: {result.hello_eq_empty}')
    print()

    # Test 2e: Debug ?= behavior with None
    print('Test 2e: Debug ?= with None parameter')
    print('-' * 60)

    debug_query2 = """\
        with
            resource_id := <optional str>$resource_id
        select {
            resource_id_value := resource_id,
            resource_id_exists := exists resource_id,
            test_str := 'hello',
            hello_eq_param := 'hello' ?= resource_id
        }"""

    result = client.query_single(debug_query2, resource_id=None)
    print(f'resource_id_value: {result.resource_id_value}')
    print(f'resource_id_exists: {result.resource_id_exists}')
    print(f'test_str: {result.test_str}')
    print(f'hello ?= resource_id: {result.hello_eq_param}')
    print()

    # Test 2f: Test ?= with actual values to verify operator works
    print('Test 2f: Verify ?= operator with actual values')
    print('-' * 60)

    debug_query3 = """\
        select {
            same := 'hello' ?= 'hello',
            diff := 'hello' ?= 'world',
            empty_str := 'hello' ?= <str>{},
            coalesce_result := <str>{} ?? 'fallback',
            manual_expansion := 'hello' = (<str>{} ?? 'hello')
        }"""

    result = client.query_single(debug_query3)
    print(f"'hello' ?= 'hello': {result.same}")
    print(f"'hello' ?= 'world': {result.diff}")
    print(f"'hello' ?= <str>{{}}: {result.empty_str}")
    print(f"<str>{{}} ?? 'fallback': {result.coalesce_result}")
    print(f"'hello' = (<str>{{}} ?? 'hello'): {result.manual_expansion}")
    print()

    # Test 3: First, find an actual resource_id for this user
    print('Test 3: Find existing pending requests for this user')
    print('-' * 60)

    find_query = """\
        select AuthorizationRequest {
            id,
            resource_type,
            resource_id,
            status
        }
        filter
            .user.telegram_id = <int64>$telegram_id
            and .status = AuthStatus.pending"""

    requests = client.query(find_query, telegram_id=telegram_id)
    for req in requests:
        print(f'  - resource_type: {req.resource_type}, resource_id: {req.resource_id}')
    print()

    if requests:
        # Test 4: Fixed query WITH specific resource_id
        first_req = requests[0]
        print(f'Test 4: Fixed query WITH resource_id="{first_req.resource_id}"')
        print('-' * 60)

        result = client.query_single(
            fixed_query,
            telegram_id=telegram_id,
            resource_type=resource_type,
            status=status,
            resource_id=first_req.resource_id,
        )
        print(f'Result: {result}')
        print()

        # Test 5: Fixed query WITH wrong resource_id
        print('Test 5: Fixed query WITH wrong resource_id="nonexistent"')
        print('-' * 60)

        result = client.query_single(
            fixed_query,
            telegram_id=telegram_id,
            resource_type=resource_type,
            status=status,
            resource_id='nonexistent',
        )
        print(f'Result: {result}')
        print()

    print('=' * 60)
    print('Done!')


if __name__ == '__main__':
    main()
