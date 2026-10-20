import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { initD0Helpers } from './helpers'
import D0App from './App.vue'

const app = createApp(D0App)
app.use(ElementPlus)
app.mount('#app')
initD0Helpers()
