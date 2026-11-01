# bsh_extensions

The official BSH extension market. The host reads `index.json`; packages live
under `packages/<id>/<version>/` and are installed into the normal hashed store
with community trust.

~~~text
bsh ext market
bsh ext market install com.example.hello
~~~

See `docs/bsh-extension-market.md` in the BOS repository for the index contract.
