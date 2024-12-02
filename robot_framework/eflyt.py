"""This module contains all logic related to the Eflyt system."""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueStatus
from itk_dev_shared_components.eflyt import eflyt_case, eflyt_search
from itk_dev_shared_components.eflyt.eflyt_case import Case
from robot_framework import config, letters


def filter_cases(cases: list[Case]) -> list[Case]:
    """Filter cases from the case table.

    Args:
        cases: A list of cases to filter.

    Returns:
        A list of filtered case objects.
    """
    filtered_cases = [
        case for case in cases
        if "Logivært" in case.case_types
    ]

    return filtered_cases


def handle_case(browser: webdriver.Chrome, case: Case, orchestrator_connection: OrchestratorConnection) -> None:
    """Handle a single case with all steps included.

    Args:
        browser: The webdriver browser object.
        case: The case to handle.
        orchestrator_connection: The connection to Orchestrator.
    """
    if not check_queue(case, orchestrator_connection):
        return

    # Create a queue element to indicate the case is being handled
    queue_element = orchestrator_connection.create_queue_element(config.QUEUE_NAME, reference=case.case_number)
    orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.IN_PROGRESS)

    orchestrator_connection.log_info(f"Beginning case: {case.case_number}")

    eflyt_search.open_case(browser, case.case_number)

    if not verify_single_letter_for_host(browser):
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sprunget over fordi breve ikke består af en enkelt logiværtserklæring.")
        orchestrator_connection.log_info("Skipping: Number of letters on case.")
        return

    if send_letter_to_anmelder(browser):
        eflyt_case.add_note(browser, "Orienteringsbrev om afsendt logiværtserklæring sendt til anmelder.")
    else:
        eflyt_case.add_note(browser, "Orienteringsbrev kunne ikke sendes til anmelder, da de ikke er tilmeldt digital post.")
        orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Anmelder kan ikke modtage Digital Post.")
        return

    orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message="Sag færdigbehandlet.")


def verify_single_letter_for_host(browser: webdriver.Chrome) -> bool:
    """Find elements of letters ready to be sent and check whether a single letter with title containing 'Logitværtserklæring' exists.

    Args:
        browser: Browser driver to use.

    Returns:
        Does a single letter with title containing 'Logitværtserklæring' exists.
    """
    # Find the letter buttons and make sure there is only one
    followup_table = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_moPersonTab_gvManuelOpfolgning")
    letter_buttons = followup_table.find_elements(By.XPATH, '//input[@src="../Images/eFlyt/iconDocument.gif"]')
    if len(letter_buttons) != 1:
        return False

    # Check that the text is as expected
    next_td = letter_buttons[0].find_element(By.XPATH, './ancestor::td/following-sibling::td[1]')
    span = next_td.find_element(By.XPATH, './/span')
    return "Logiværtserklæring" in span.text


def check_queue(case: Case, orchestrator_connection: OrchestratorConnection) -> bool:
    """Check if a case has been handled before by checking the job queue i Orchestrator.

    Args:
        case: The case to check.
        orchestrator_connection: The connection to Orchestrator.

    Return:
        bool: True if the element should be handled, False if it should be skipped.
    """
    queue_elements = orchestrator_connection.get_queue_elements(queue_name=config.QUEUE_NAME, reference=case.case_number)

    if len(queue_elements) == 0:
        return True

    # If the case has been tried more than once before skip it
    if len(queue_elements) > 1:
        orchestrator_connection.log_info("Skipping: Case has failed in the past.")
        return False

    # If it has been marked as done, skip it
    if queue_elements[0].status == QueueStatus.DONE:
        orchestrator_connection.log_info("Skipping: Case already marked as done.")
        return False

    return True


def send_letter_to_anmelder(browser: webdriver.Chrome) -> bool:
    """Open the 'Breve' tab and send a letter to the anmelder.

    Args:
        browser: The webdriver browser object.
        original_letter: The title of the original logiværtserklæring.

    Returns:
        bool: True if the letter was sent.
    """
    eflyt_case.change_tab(browser, tab_index=3)

    click_letter_template(browser, "- Individuelt brev")

    # Select the anmelder as the receiver
    select_letter_receiver(browser, "(anmelder)")

    # Click 'Send brev'
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_btnSendBrev").click()

    # Insert the correct letter text
    text_area = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_txtStandardText")
    text_area.clear()
    text_area.send_keys(letters.LETTER_TO_ANMELDER)
    # Click 'Ok'
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_btnOK").click()

    # Check if a warning appears
    if check_digital_post_warning(browser):
        # Click 'Nej'
        browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_btnDeleteLetter").click()
        return False

    # Click 'Ja'
    browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_btnSaveLetter").click()
    return True


def click_letter_template(browser: webdriver.Chrome, letter_name: str):
    """Click the letter template with the given name under the "Breve" tab.

    Args:
        browser: The webdriver browser object.
        letter_name: The literal name of the letter template to click.

    Raises:
        ValueError: If the letter wasn't found in the list.
    """
    letter_table = browser.find_element(By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_GridViewBreveNew")
    rows = letter_table.find_elements(By.TAG_NAME, "tr")

    for row in rows:
        text = row.find_element(By.XPATH, "td[2]").text
        if text == letter_name:
            row.find_element(By.XPATH, "td[1]/input").click()
            return

    raise ValueError(f"Template with the name '{letter_name}' was not found.")


def select_letter_receiver(browser: webdriver.Chrome, receiver_name: str) -> None:
    """Select the receiver for the letter. The search is fuzzy so it's only checked
    if the options contains the receiver name.

    I some cases there's only one option for the receiver in which
    case there's a text label instead of a select element. In this
    case the predefined name is still checked against the desired receiver.

    Args:
        browser: The webdriver browser object.
        receiver_name: The name of the receiver to select.

    Raises:
        ValueError: If the given name isn't found in the select options.
        ValueError: If the given name doesn't match the static label.
    """
    # Check if there is a select for the receiver name
    try:
        # Wait for the dropdown to be present
        name_select_element = WebDriverWait(browser, 2).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_ddlModtager"))
        )
        name_select = Select(name_select_element)

        # Wait until the dropdown has more than one option
        WebDriverWait(browser, 2).until(lambda browser: len(name_select.options) > 1)

        for i, option in enumerate(name_select.options):
            if receiver_name in option.text:
                name_select.select_by_index(i)
                return

        raise ValueError(f"'{receiver_name}' wasn't found on the list of possible receivers.")

    except TimeoutException:
        pass  # Continue to the next check if the dropdown is not found

    # If there's simply a label for the receiver, check if the name matches
    try:
        name_label = WebDriverWait(browser, 2).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder2_ptFanePerson_bcPersonTab_lblModtagerName"))
        )
        if receiver_name not in name_label.text:
            raise ValueError(f"'{receiver_name}' didn't match the predefined receiver.")
    except TimeoutException as exc:
        raise ValueError("Receiver name label did not load in time.") from exc


def check_digital_post_warning(browser: webdriver.Chrome) -> bool:
    """Check if a red warning text has appeared warning that
    a letter must be sent manually.

    Args:
        browser: The webdriver browser object.

    Returns:
        bool: True if the warning has appeared.
    """
    warning_text = browser.find_elements(By.XPATH, "//font[@color='red']")
    return len(warning_text) != 0 and "Dokumentet skal sendes manuelt" in warning_text[0].text
