# Registry Cache

A simple Docker Registry configured as a pull-through cache for ghcr.io images.

## Usage

To use the registry cache in your deployments, modify your image references to use the local registry:

**Original image reference:**
```
ghcr.io/trailofbits/buttercup/buttercup-orchestrator:main
```

**Using the cache:**
```
buttercup-registry-cache/trailofbits/buttercup/buttercup-orchestrator:main
```

or with release name:

```
<release-name>-registry-cache/trailofbits/buttercup/buttercup-orchestrator:main
```

The registry uses HTTP on port 80.
