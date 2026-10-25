import { configure } from '@testing-library/react'

// findBy*/waitFor give up after 1 s by default, which a busy machine (or CI runner) can exceed while jsdom
// renders; a missing element still fails, only later.
configure({ asyncUtilTimeout: 5000 })
