def pyflex_warning():
    warning = (f'----------------------------------WARNING-----------------------------------------------\n'
              'It is highly recommended to use the Reflexer App or Geb-js to perform SAFE modifications\n'
              'Pyflex uses unmanaged SAFEs, which are not supported by the App or geb-js.\n'
              'If you use pyflex to open or modify a SAFE, it will be unaccessible in the App or geb-js!\n')

    answer = ""
    while answer not in ["y", "n"]:
        print(warning)
        answer = input("OK to continue [Y/N]? ").lower()
    return answer == "y"
