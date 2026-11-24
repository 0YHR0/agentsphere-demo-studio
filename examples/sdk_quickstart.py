"""Direct official SDK example, separate from the Studio runtime ledger."""
import os
import agentsphere_e2b_patch  # Must precede e2b imports.
from e2b import Sandbox


def main():
    options = dict(api_key=os.environ['E2B_API_KEY'],api_url=os.environ['E2B_API_URL'],
                   sandbox_url=os.environ['E2B_SANDBOX_URL'])
    # The caller supplies its own templateID:buildID and Gateway.
    sb = Sandbox.create(os.environ['AGENTSPHERE_TEMPLATE_REF'],timeout=600,**options)
    print('Created sandbox:',sb.sandbox_id)
    try:
        value=sb.commands.run('echo hello-agentsphere; id',user='root',cwd='/')
        print(value.exit_code,value.stdout)
        sb.files.write('/tmp/sdk-quickstart.txt','hello-agentsphere\n',user='root')
        assert sb.files.read('/tmp/sdk-quickstart.txt',user='root')=='hello-agentsphere\n'
    except Exception:
        print('Failed; sandbox retained for inspection:',sb.sandbox_id)
        raise
    else:
        # Deletes only the sandbox this example just created.
        sb.kill()
        print('Deleted sandbox:',sb.sandbox_id)


if __name__=='__main__':main()
